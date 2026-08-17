"""Document processing pipeline: claim → download → parse → chunk → embed → persist.

One session per document (docs/ingestion.md §3, research.md R6); every write
runs under the owner's RLS claim via _switch_to_owner (docs/multi-tenancy.md
§2/§3, contracts/worker.md §1). Failure classes per contracts/ai-provider.md
§6. The row's status is the cancellation signal: the pipeline re-checks it
between stages and aborts with 'cancelled' when the owner cancelled or deleted
the document (docs/ingestion.md §1).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from io import BytesIO
from logging import getLogger
from time import perf_counter
from typing import Literal

from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.providers.ai.base import (
    AIProvider,
    AIProviderError,
    clamp_chunk_size_chars,
    is_transient_status,
)
from app.providers.storage.base import StorageError, StorageProvider
from app.services.chunker import CHARS_PER_TOKEN, Chunk, ParseError, chunk_pages

logger = getLogger(__name__)

RLS_ROLE = "contextly_app"

Outcome = Literal["ready", "retry", "failed", "stale", "cancelled"]

_CLAIM = text("SELECT * FROM worker_claim_next(:lease_seconds)")

_INSERT_CHUNK = text(
    """
    insert into document_chunks
        (document_id, chunk_index, content, page_number, token_count, metadata, embedding)
    values (:document_id, :chunk_index, :content, :page_number, :token_count, :metadata, :embedding)
    """
)

_DELETE_CHUNKS = text(
    """
    delete from document_chunks
    where document_id = :document_id
    """
)

_FINALIZE = text(
    """
    update documents
    set status = 'ready',
        total_chunks = :total_chunks,
        status_error = null,
        lease_until = null,
        updated_at = now()
    where id = :id and status = 'processing' and deleted_at is null
    returning id
    """
)

_FAIL_PERMANENT = text(
    """
    update documents
    set status = 'failed', status_error = :message, lease_until = null, updated_at = now()
    where id = :id and deleted_at is null
    """
)

_FAIL_TRANSIENT = text(
    """
    update documents
    set status = 'uploaded',
        retry_count = :retry_count,
        status_error = :message,
        lease_until = now() + make_interval(secs => :backoff_seconds),
        updated_at = now()
    where id = :id and deleted_at is null
    """
)

_EXHAUST_RETRIES = text(
    """
    update documents
    set status = 'failed',
        retry_count = :retry_count,
        status_error = :message,
        lease_until = null,
        updated_at = now()
    where id = :id and deleted_at is null
    """
)

_CHECK_ACTIVE = text(
    """
    select 1 from documents
    where id = :id and status = 'processing' and deleted_at is null
    """
)


@dataclass(frozen=True)
class ClaimedDocument:
    """The identity fields worker_claim_next returns — never document content."""

    id: uuid.UUID
    user_id: uuid.UUID
    storage_path: str
    filename: str
    retry_count: int


class StaleClaimError(Exception):
    """The claimed document is gone or was re-claimed; persist must roll back."""


async def _check_active(db: AsyncSession, claimed: ClaimedDocument) -> bool:
    """True while the row is still 'processing' — cancel/delete flips it away
    (the stop signal, docs/ingestion.md §1). Caller switched to the owner."""
    result = await db.execute(_CHECK_ACTIVE, {"id": str(claimed.id)})
    return result.one_or_none() is not None


async def claim_next(db: AsyncSession, *, lease_seconds: int) -> ClaimedDocument | None:
    """Atomically claim one eligible document (contracts/worker.md §2)."""
    result = await db.execute(_CLAIM, {"lease_seconds": lease_seconds})
    row = result.one_or_none()
    if row is None:
        return None
    return ClaimedDocument(
        id=row.id,
        user_id=row.user_id,
        storage_path=row.storage_path,
        filename=row.filename,
        retry_count=row.retry_count,
    )


def _clean_page_text(text: str) -> str:
    """Replace C0 controls (NUL etc.) from broken PDF encodings — Postgres cannot
    store NUL and the controls act as word separators (docs/ingestion.md §2)."""
    return "".join(ch if ch >= " " or ch in "\t\n\r" else " " for ch in text)


def parse_pdf(data: bytes) -> list[str]:
    """Extract per-page text (research.md R2). Runs in a thread by the caller."""
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:  # noqa: BLE001 - map any decrypt failure
                raise ParseError("corrupt or unreadable PDF") from exc
        pages = [_clean_page_text(page.extract_text() or "") for page in reader.pages]
    except (PdfReadError, PdfStreamError, ValueError, TypeError) as exc:
        raise ParseError("corrupt or unreadable PDF") from exc
    return pages


async def _switch_to_owner(db: AsyncSession, claimed: ClaimedDocument) -> None:
    """Run the rest of the transaction as the runtime role under the owner's RLS claim."""
    await db.execute(text(f"SET LOCAL ROLE {RLS_ROLE}"))
    await db.execute(
        text("SELECT set_config('request.jwt.claim.sub', :sub, true)"),
        {"sub": str(claimed.user_id)},
    )


async def _fail_permanent(
    db: AsyncSession, claimed: ClaimedDocument, message: str
) -> Outcome:
    await db.execute(_FAIL_PERMANENT, {"id": str(claimed.id), "message": message})
    return "failed"


async def _fail_transient(
    db: AsyncSession,
    settings: Settings,
    claimed: ClaimedDocument,
    message: str,
) -> Outcome:
    retry_count = claimed.retry_count + 1
    if retry_count < settings.worker_max_retries:
        backoff = settings.worker_retry_backoff_seconds_list[
            min(retry_count - 1, len(settings.worker_retry_backoff_seconds_list) - 1)
        ]
        await db.execute(
            _FAIL_TRANSIENT,
            {
                "id": str(claimed.id),
                "retry_count": retry_count,
                "message": message,
                "backoff_seconds": backoff,
            },
        )
        return "retry"
    await db.execute(
        _EXHAUST_RETRIES,
        {"id": str(claimed.id), "retry_count": retry_count, "message": message},
    )
    return "failed"


async def _persist(
    db: AsyncSession,
    claimed: ClaimedDocument,
    chunks: list[Chunk],
    embeddings: list[list[float]],
) -> None:
    # Clear first, same transaction: a re-run never collides with stale rows.
    await db.execute(_DELETE_CHUNKS, {"document_id": str(claimed.id)})
    for index, chunk in enumerate(chunks):
        await db.execute(
            _INSERT_CHUNK,
            {
                "document_id": str(claimed.id),
                "chunk_index": index,
                "content": chunk.content,
                "page_number": chunk.page_start,
                "token_count": chunk.token_count,
                "metadata": f'{{"page_start": {chunk.page_start}, "page_end": {chunk.page_end}}}',
                "embedding": str(embeddings[index]),
            },
        )
    result = await db.execute(
        _FINALIZE, {"id": str(claimed.id), "total_chunks": len(chunks)}
    )
    if result.one_or_none() is None:
        raise StaleClaimError("document deleted or re-claimed during processing")


async def process_claimed_document(
    db: AsyncSession,
    storage: StorageProvider,
    settings: Settings,
    claimed: ClaimedDocument,
    ai: AIProvider,
) -> Outcome:
    """Run one claimed document through the pipeline (contracts/worker.md §4–5).

    Failure classes (contracts/ai-provider.md §6): ParseError and deterministic
    embed rejections are permanent → failed now; storage/embed failures
    (429/5xx) and unexpected exceptions are transient → deferred-lease retry,
    then failed. Unexpected exceptions never escape (F1). The owner's
    cancel/delete is polled between stages — the run then aborts as
    'cancelled' and nothing persists.
    """
    await _switch_to_owner(db, claimed)
    started = perf_counter()
    try:
        try:
            data = await storage.download(key=claimed.storage_path)
        except StorageError as exc:
            message = f"storage read failed: {exc}"
            logger.warning(
                "doc %s transient failure | class=transient | %s", claimed.id, message
            )
            return await _fail_transient(db, settings, claimed, message)

        if not await _check_active(db, claimed):
            logger.info("doc %s cancelled | stage=parse", claimed.id)
            return "cancelled"

        try:
            pages = await asyncio.to_thread(parse_pdf, data)
        except ParseError as exc:
            message = str(exc)
            logger.warning(
                "doc %s permanent failure | class=permanent | %s", claimed.id, message
            )
            return await _fail_permanent(db, claimed, message)

        try:
            chunk_size_chars = clamp_chunk_size_chars(
                round(settings.chunk_size_tokens * CHARS_PER_TOKEN),
                ai.embedding_max_input_tokens,
            )
            chunks = chunk_pages(
                pages,
                chunk_size_chars=chunk_size_chars,
                overlap_chars=round(settings.chunk_overlap_tokens * CHARS_PER_TOKEN),
            )
        except ParseError as exc:
            message = str(exc)
            logger.warning(
                "doc %s permanent failure | class=permanent | %s", claimed.id, message
            )
            return await _fail_permanent(db, claimed, message)

        batch_size = settings.embedding_batch_size
        embeddings: list[list[float]] = []
        for start in range(0, len(chunks), batch_size):
            if not await _check_active(db, claimed):
                logger.info(
                    "doc %s cancelled | stage=embed | batches_done=%d/%d",
                    claimed.id,
                    len(embeddings),
                    len(chunks),
                )
                return "cancelled"
            batch = [chunk.content for chunk in chunks[start : start + batch_size]]
            try:
                embeddings.extend(await ai.embed(batch, batch_size=len(batch)))
            except AIProviderError as exc:
                if not is_transient_status(exc.status_code):
                    message = f"embedding configuration error: {exc}"
                    logger.warning(
                        "doc %s permanent failure | class=permanent | %s",
                        claimed.id,
                        message,
                    )
                    return await _fail_permanent(db, claimed, message)
                message = f"embedding failed: {exc}"
                logger.warning(
                    "doc %s transient failure | class=transient | %s", claimed.id, message
                )
                return await _fail_transient(db, settings, claimed, message)
            except Exception as exc:
                message = f"embedding failed: {exc}"
                logger.warning(
                    "doc %s transient failure | class=transient | %s", claimed.id, message
                )
                return await _fail_transient(db, settings, claimed, message)

        if not await _check_active(db, claimed):
            logger.info("doc %s cancelled | stage=persist | chunks=%d", claimed.id, len(chunks))
            return "cancelled"

        try:
            async with db.begin_nested():
                await _persist(db, claimed, chunks, embeddings)
        except StaleClaimError:
            logger.warning("doc %s stale claim — rolling back persist", claimed.id)
            return "stale"
    except Exception as exc:
        message = f"unexpected processing failure: {exc}"
        logger.exception(
            "doc %s unexpected failure | class=transient | %s",
            claimed.id,
            message,
        )
        return await _fail_transient(db, settings, claimed, message)

    logger.info(
        "doc %s done | stage=finalize | duration_ms=%.0f | page_count=%d | chunk_count=%d | total_tokens=%d | embedding_model=%s",
        claimed.id,
        (perf_counter() - started) * 1000,
        len(pages),
        len(chunks),
        sum(chunk.token_count for chunk in chunks),
        ai.embedding_model,
    )
    return "ready"


async def rearm_lease(
    db: AsyncSession, claimed: ClaimedDocument, lease_seconds: int
) -> None:
    """Heartbeat: extend the claim's lease under the owner's RLS session (contracts §3)."""
    await _switch_to_owner(db, claimed)
    await db.execute(
        text(
            "update documents set lease_until = now() + make_interval(secs => :lease)"
            " where id = :id and status = 'processing'"
        ),
        {"lease": lease_seconds, "id": str(claimed.id)},
    )
