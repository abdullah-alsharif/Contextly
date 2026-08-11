"""Retrieval engine: top-K semantic search scoped to a conversation's documents.

Contract: specs/007-rag-retrieval-engine/contracts/retrieval.md §1, following
docs/rag.md §3 (query), §2 (defaults: top-K 6, L2, ef_search 40), §5 (source
metadata), §7 (empty/failure handling), and docs/security.md §2/§4 (404
ownership semantics, question cap). Runs on the caller's RLS-scoped session
set by get_current_user — the database stays the enforced boundary
(docs/multi-tenancy.md §2 belt-and-suspenders: SQL filters + RLS).

Pre-LLM only: this module never calls a generation service (docs/roadmap.md
Phase 6-7); it returns chunks, not answers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from logging import getLogger
from time import perf_counter

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security.identity import Identity
from app.providers.ai.base import AIProvider, AIProviderError

logger = getLogger(__name__)

_CHECK_CONVERSATION = text(
    """
    select 1 from conversations
    where id = :conversation_id and user_id = :user_id and deleted_at is null
    """
)

_SEARCH_READY = text(
    """
    select
      c.content,
      c.page_number,
      c.chunk_index,
      d.id   as document_id,
      d.filename,
      1 - (c.embedding <-> :query_vec) as similarity
    from document_chunks c
    join documents d on d.id = c.document_id
    where d.status = 'ready'
      and d.user_id = :user_id                       -- tenant boundary (belt & suspenders)
      and d.deleted_at is null
      and c.document_id in (                         -- conversation document selection
          select cd.document_id from conversation_documents cd
          where cd.conversation_id = :conversation_id
      )
    order by c.embedding <-> :query_vec asc          -- L2; ascending = closest
    limit :top_k
    """
)


@dataclass(frozen=True)
class RetrievalHit:
    """One ranked chunk with source metadata (docs/rag.md §5)."""

    document_id: uuid.UUID
    filename: str
    page_number: int | None
    chunk_index: int
    similarity: float
    content: str


class ConversationNotFoundError(Exception):
    """Conversation missing, not owned, or deleted (→ 404, deliberately ambiguous)."""


class QuestionEmbeddingError(Exception):
    """Question embedding failed after retries (→ 502, upstream AI failure)."""


async def _embed_question(ai: AIProvider, question: str) -> list[float]:
    """Embed the question; one retry on transient failures (docs/rag.md §7).

    401/403 are configuration errors → never retried. Any other failure gets
    exactly one retry before surfacing as QuestionEmbeddingError.
    """
    for attempt in range(2):
        try:
            return (await ai.embed([question]))[0]
        except AIProviderError as exc:
            if attempt == 0 and exc.status_code not in (401, 403):
                continue
            raise QuestionEmbeddingError(f"question embedding failed: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - provider boundary: never leak
            if attempt == 0:
                continue
            raise QuestionEmbeddingError(f"question embedding failed: {exc}") from exc
    raise AssertionError("unreachable")  # pragma: no cover


async def search_ready_documents(
    db: AsyncSession,
    ai: AIProvider,
    settings: Settings,
    *,
    identity: Identity,
    conversation_id: uuid.UUID,
    question: str,
    top_k: int | None = None,
) -> list[RetrievalHit]:
    """Return the top-K chunks most similar to the question, scoped strictly.

    Scope (docs/rag.md §3): documents owned by the caller, status 'ready',
    and linked to the conversation. An unowned/missing/deleted conversation
    raises ConversationNotFoundError (404 semantics, docs/security.md §2).
    Zero qualifying chunks → [] (never an error; docs/rag.md §7).
    """
    result = await db.execute(
        _CHECK_CONVERSATION,
        {
            "conversation_id": str(conversation_id),
            "user_id": str(identity.user_id),
        },
    )
    if result.one_or_none() is None:
        raise ConversationNotFoundError("conversation not found")

    resolved_top_k = settings.retrieval_top_k if top_k is None else top_k

    started = perf_counter()
    query_vec = await _embed_question(ai, question)

    # HNSW search effort, transaction-local (docs/rag.md §2 ef_search 40).
    await db.execute(
        text("SELECT set_config('hnsw.ef_search', :ef, true)"),
        {"ef": str(settings.retrieval_ef_search)},
    )

    rows = await db.execute(
        _SEARCH_READY,
        {
            "query_vec": str(query_vec),
            "user_id": str(identity.user_id),
            "conversation_id": str(conversation_id),
            "top_k": resolved_top_k,
        },
    )
    hits = [
        RetrievalHit(
            document_id=row.document_id,
            filename=row.filename,
            page_number=row.page_number,
            chunk_index=row.chunk_index,
            similarity=float(row.similarity),
            content=row.content,
        )
        for row in rows.all()
    ]
    elapsed_ms = (perf_counter() - started) * 1000

    logger.info(
        "retrieval | class=%s | user=%s | conversation=%s | question=%s | "
        "top_k=%d | hits=%d | scores=%s | retrieval_ms=%.1f | embedding_model=%s",
        "empty" if not hits else "hit",
        identity.user_id,
        conversation_id,
        question,
        resolved_top_k,
        len(hits),
        [round(hit.similarity, 4) for hit in hits],
        elapsed_ms,
        ai.embedding_model,
    )
    return hits
