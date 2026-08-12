"""Documents service: upload validation, CRUD, storage coordination.

Contract: specs/004-document-upload-storage/contracts/documents.md, following
docs/api.md §2 and docs/ingestion.md §2/§7. All queries are scoped to the
caller (user_id = current_user) and run under the RLS session established by
get_current_user — the database stays the enforced boundary
(docs/multi-tenancy.md §2 belt-and-suspenders).

Upload order (research.md R3): validate → insert row → upload object → 201.
An upload failure rolls the row back (get_db rolls back on exception).
Delete order (research.md R4): owned-row lookup → soft-delete → remove object.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from logging import getLogger
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security.identity import Identity
from app.providers.storage.base import StorageError, StorageProvider, validate_key

logger = getLogger(__name__)

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

_INSERT_DOCUMENT = text(
    """
    insert into documents (id, user_id, filename, storage_path, file_size_bytes, mime_type)
    values (:id, :user_id, :filename, :storage_path, :file_size_bytes, :mime_type)
    returning id, filename, status, file_size_bytes, total_chunks, status_error,
              created_at, updated_at
    """
)

_LIST_DOCUMENTS_BASE = text(
    """
    select id, filename, status, file_size_bytes, total_chunks, status_error,
           created_at, updated_at
    from documents
    where user_id = :user_id and deleted_at is null
    order by created_at desc
    """
)

_LIST_DOCUMENTS_BY_STATUS = text(
    """
    select id, filename, status, file_size_bytes, total_chunks, status_error,
           created_at, updated_at
    from documents
    where user_id = :user_id and deleted_at is null and status = :status
    order by created_at desc
    """
)

_GET_DOCUMENT = text(
    """
    select id, filename, status, file_size_bytes, total_chunks, status_error,
           created_at, updated_at, storage_path
    from documents
    where id = :document_id and user_id = :user_id and deleted_at is null
    """
)

_SOFT_DELETE = text(
    """
    update documents
    set deleted_at = now(), updated_at = now()
    where id = :document_id and user_id = :user_id and deleted_at is null
    returning storage_path
    """
)

_REPROCESS = text(
    """
    update documents
    set status = 'uploaded',
        total_chunks = null,
        status_error = null,
        retry_count = 0,
        lease_until = null,
        updated_at = now()
    where id = :document_id and user_id = :user_id
      and deleted_at is null and status = 'failed'
    returning id, filename, status, file_size_bytes, total_chunks, status_error,
              created_at, updated_at
    """
)

_PURGE_CHUNKS = text("delete from document_chunks where document_id = :document_id")


class InvalidUploadError(Exception):
    """Upload rejected by a validation rule (→ 400)."""


class UploadTooLargeError(Exception):
    """Upload exceeds the size cap (→ 413)."""


class UploadFailedError(Exception):
    """Storage backend rejected the object (→ 502)."""


class SignedUrlError(Exception):
    """Storage backend refused to sign a download URL (→ 502, upstream)."""


class DocumentNotFoundError(Exception):
    """Document missing, not owned, or deleted (→ 404, deliberately ambiguous)."""


class ReprocessNotAllowedError(Exception):
    """Document exists but is not in a reprocessable state (→ 400)."""


def sanitize_filename(filename: str) -> str:
    """Strip path components + control chars; display name only (docs/security.md §3)."""
    name = Path(filename.replace("\\", "/")).name
    name = _CONTROL_CHARS.sub("", name).strip()
    return name


async def create_document(
    db: AsyncSession,
    storage: StorageProvider,
    settings: Settings,
    identity: Identity,
    *,
    filename: str,
    content_type: str,
    data: bytes,
) -> dict[str, Any]:
    """Validate, persist, and store an uploaded document (contracts/documents.md §2)."""
    display_name = sanitize_filename(filename)
    if not display_name:
        raise InvalidUploadError("filename is missing or invalid")
    if not display_name.lower().endswith(".pdf"):
        raise InvalidUploadError("only PDF files (.pdf) are accepted")
    if (content_type or "").lower() != "application/pdf":
        raise InvalidUploadError("content-type must be application/pdf")
    if not data:
        raise InvalidUploadError("file is empty")
    if data[:5] != b"%PDF-":
        raise InvalidUploadError("file is not a readable PDF")
    if len(data) > settings.upload_max_bytes:
        raise UploadTooLargeError(
            f"file exceeds the {settings.upload_max_bytes} byte upload limit"
        )

    document_id = uuid.uuid4()
    storage_path = f"{identity.user_id}/docs/{document_id}.pdf"
    validate_key(storage_path, identity.user_id)

    result = await db.execute(
        _INSERT_DOCUMENT,
        {
            "id": str(document_id),
            "user_id": str(identity.user_id),
            "filename": display_name,
            "storage_path": storage_path,
            "file_size_bytes": len(data),
            "mime_type": "application/pdf",
        },
    )
    row = result.one()

    try:
        await storage.upload(
            key=storage_path,
            data=data,
            content_type="application/pdf",
        )
    except StorageError as exc:
        raise UploadFailedError("upload failed") from exc

    return _serialize(row)


async def list_documents(
    db: AsyncSession,
    identity: Identity,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Return the caller's documents, newest first, optionally filtered by status."""
    query = _LIST_DOCUMENTS_BY_STATUS if status is not None else _LIST_DOCUMENTS_BASE
    params: dict[str, Any] = {"user_id": str(identity.user_id)}
    if status is not None:
        params["status"] = status
    result = await db.execute(query, params)
    return [_serialize(row) for row in result.all()]


async def get_document(
    db: AsyncSession,
    identity: Identity,
    document_id: uuid.UUID,
) -> dict[str, Any]:
    """Return the caller's document detail, or raise DocumentNotFoundError."""
    result = await db.execute(
        _GET_DOCUMENT,
        {"document_id": str(document_id), "user_id": str(identity.user_id)},
    )
    row = result.one_or_none()
    if row is None:
        raise DocumentNotFoundError("document not found")
    return _serialize(row)


async def delete_document(
    db: AsyncSession,
    storage: StorageProvider,
    identity: Identity,
    document_id: uuid.UUID,
) -> None:
    """Soft-delete the row, purge chunks, and remove the storage object.

    The chunk purge happens in the same transaction as the soft delete so no
    chunks survive for a deleted document (docs/ingestion.md §7, research.md
    R5, spec US4). The row is hidden first so the delete is safe even if
    storage is degraded; a storage failure is logged and the object is
    reclaimed later (research.md R4).
    """
    result = await db.execute(
        _SOFT_DELETE,
        {"document_id": str(document_id), "user_id": str(identity.user_id)},
    )
    row = result.one_or_none()
    if row is None:
        raise DocumentNotFoundError("document not found")
    await db.execute(_PURGE_CHUNKS, {"document_id": str(document_id)})
    storage_path = row.storage_path
    try:
        await storage.delete(key=storage_path)
    except StorageError as exc:
        logger.warning(
            "storage delete failed for %s (orphan reclaim is Phase 9): %s",
            storage_path,
            exc,
        )


async def reprocess_document(
    db: AsyncSession,
    identity: Identity,
    document_id: uuid.UUID,
) -> dict[str, Any]:
    """Reset a failed document to 'uploaded' and purge its chunks so the worker
    re-runs the full pipeline (docs/ingestion.md §7 re-indexing).

    Owner-only scoped: a foreign/missing id raises DocumentNotFoundError (404).
    Only `failed` documents are eligible — everything else raises
    ReprocessNotAllowedError (400). Chunk purge runs in the same transaction
    as the status reset, so a reprocessed document never shows stale chunks.
    """
    result = await db.execute(
        _REPROCESS,
        {"document_id": str(document_id), "user_id": str(identity.user_id)},
    )
    row = result.one_or_none()
    if row is None:
        existing = await db.execute(
            _GET_DOCUMENT,
            {"document_id": str(document_id), "user_id": str(identity.user_id)},
        )
        if existing.one_or_none() is None:
            raise DocumentNotFoundError("document not found")
        raise ReprocessNotAllowedError("only failed documents can be reprocessed")
    await db.execute(_PURGE_CHUNKS, {"document_id": str(document_id)})
    return _serialize(row)


async def get_document_download_url(
    db: AsyncSession,
    storage: StorageProvider,
    identity: Identity,
    document_id: uuid.UUID,
    *,
    ttl_seconds: int,
) -> tuple[str, datetime]:
    """Mint a short-lived signed URL for one of the caller's documents.

    docs/api.md §5 (5 min), docs/multi-tenancy.md §4: objects are never public;
    this returns a signed URL that expires quickly. Owner-only — a foreign or
    missing id raises DocumentNotFoundError (404, docs/security.md §2
    anti-enumeration), so a caller can never learn another tenant's object key.

    Expiry is enforced by the storage backend that issues the token (Supabase
    validates `exp` server-side); the local provider is dev/CI-only and does not
    enforce expiry (documented risk, docs/security.md §7). `expires_at` is
    computed from the provider's own notion where available; a signing failure
    raises SignedUrlError (502) without leaking the storage path.
    """
    result = await db.execute(
        _GET_DOCUMENT,
        {"document_id": str(document_id), "user_id": str(identity.user_id)},
    )
    row = result.one_or_none()
    if row is None:
        raise DocumentNotFoundError("document not found")
    try:
        url = await storage.signed_url(
            key=row.storage_path, expires_in_seconds=ttl_seconds
        )
    except StorageError as exc:
        raise SignedUrlError("signed URL issuance failed") from exc
    # TTL is validated to a short, supra-provider-max-safe range (1..3600s,
    # config.py), so expires_at is never longer than the issued token's lifetime.
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    return url, expires_at


def _serialize(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "filename": row.filename,
        "status": row.status,
        "file_size_bytes": row.file_size_bytes,
        "total_chunks": row.total_chunks,
        "status_error": row.status_error,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
