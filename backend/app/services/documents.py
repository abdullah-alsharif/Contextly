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

import uuid
from datetime import datetime, timedelta, timezone
from logging import getLogger
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security.identity import Identity
from app.providers.storage.base import StorageError, StorageProvider, validate_key
from app.services.text_clean import strip_control_chars

logger = getLogger(__name__)

_INSERT_DOCUMENT = text(
    """
    insert into documents (id, user_id, filename, storage_path, file_size_bytes, mime_type, replaces_document_id)
    values (:id, :user_id, :filename, :storage_path, :file_size_bytes, :mime_type, :replaces_document_id)
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
      and deleted_at is null and status in ('failed', 'cancelled')
    returning id, filename, status, file_size_bytes, total_chunks, status_error,
              created_at, updated_at
    """
)

_CANCEL = text(
    """
    update documents
    set status = 'cancelled',
        lease_until = null,
        status_error = null,
        updated_at = now()
    where id = :document_id and user_id = :user_id
      and deleted_at is null and status in ('uploaded', 'processing')
    returning id
    """
)

_FIND_ACTIVE_DUPLICATE = text(
    """
    select id, filename
    from documents
    where user_id = :user_id and filename = :filename
      and deleted_at is null and status <> 'superseded' and status <> 'cancelled'
    order by created_at asc
    limit 1
    """
)

_SUPERSEDE = text(
    """
    update documents
    set status = 'superseded',
        superseded_from = status,  -- RHS is the pre-replace status
        lease_until = null,
        updated_at = now()
    where id = :document_id and user_id = :user_id
      and deleted_at is null and status <> 'superseded'
    returning id
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


class DownloadError(Exception):
    """Storage backend failed to serve a document's bytes (→ 502, upstream)."""


class DocumentNotFoundError(Exception):
    """Document missing, not owned, or deleted (→ 404, deliberately ambiguous)."""


class ReprocessNotAllowedError(Exception):
    """Document exists but is not in a reprocessable state (→ 400)."""


class CancelNotAllowedError(Exception):
    """Document exists but is not cancellable (not queued/processing, → 409)."""


class DuplicateDocumentError(Exception):
    """An active document with the same filename already exists (→ 409).

    Carries the existing row's id so callers can offer replace-vs-rename
    (docs/api.md §2 duplicate handling).
    """

    def __init__(self, existing_id: uuid.UUID | None, message: str) -> None:
        self.existing_id = existing_id
        super().__init__(message)


def sanitize_filename(filename: str) -> str:
    """Strip path components + control chars; display name only (docs/security.md §3)."""
    name = Path(filename.replace("\\", "/")).name
    name = strip_control_chars(name).strip()
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
    replace: bool = False,
) -> dict[str, Any]:
    """Validate, persist, and store an uploaded document (docs/ingestion.md §5).

    An active row with the same (user_id, filename) is either superseded
    (`replace=True`) or rejected with DuplicateDocumentError (409). The partial
    unique index documents_active_filename_idx closes the parallel-upload race:
    a concurrent insert surfaces as IntegrityError → 409.
    """
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

    if replace:
        replaced_id = await supersede_active_duplicates(db, identity, display_name)
    else:
        duplicate = await find_active_duplicate(db, identity, display_name)
        if duplicate is not None:
            raise DuplicateDocumentError(
                duplicate["id"],
                f'A file named "{display_name}" is already in your library',
            )
        replaced_id = None

    document_id = uuid.uuid4()
    storage_path = f"{identity.user_id}/docs/{document_id}.pdf"
    validate_key(storage_path, identity.user_id)

    try:
        result = await db.execute(
            _INSERT_DOCUMENT,
            {
                "id": str(document_id),
                "user_id": str(identity.user_id),
                "filename": display_name,
                "storage_path": storage_path,
                "file_size_bytes": len(data),
                "mime_type": "application/pdf",
                "replaces_document_id": str(replaced_id) if replaced_id else None,
            },
        )
    except IntegrityError as exc:
        raise DuplicateDocumentError(
            None,
            f'A file named "{display_name}" is already in your library',
        ) from exc
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


async def find_active_duplicate(
    db: AsyncSession,
    identity: Identity,
    filename: str,
) -> dict[str, Any] | None:
    """Return an active (non-deleted, non-superseded) row with the same name."""
    result = await db.execute(
        _FIND_ACTIVE_DUPLICATE,
        {"user_id": str(identity.user_id), "filename": filename},
    )
    row = result.one_or_none()
    return None if row is None else {"id": row.id, "filename": row.filename}


async def supersede_active_duplicates(
    db: AsyncSession,
    identity: Identity,
    filename: str,
) -> uuid.UUID | None:
    """Mark every active row with this name 'superseded' and return the last id.

    The chunk purge is deferred: the replace resolution trigger (migration
    0005) purges the old chunks when the replacement becomes 'ready' and
    restores the old status when it 'fails' or is deleted (docs/ingestion.md
    §7). Runs in the caller's transaction alongside the replacement insert, so
    a failed upload (storage error) rolls the supersede back.
    """
    replaced: uuid.UUID | None = None
    while True:
        result = await db.execute(
            _FIND_ACTIVE_DUPLICATE,
            {"user_id": str(identity.user_id), "filename": filename},
        )
        row = result.one_or_none()
        if row is None:
            return replaced
        await db.execute(
            _SUPERSEDE,
            {"document_id": str(row.id), "user_id": str(identity.user_id)},
        )
        replaced = row.id


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
    """Reset a failed or cancelled document to 'uploaded' and purge its chunks
    so the worker re-runs the full pipeline (docs/ingestion.md §7 re-indexing).

    Owner-only scoped: a foreign/missing id raises DocumentNotFoundError (404).
    Only `failed` and `cancelled` documents are eligible — everything else
    raises ReprocessNotAllowedError (400). Chunk purge runs in the same
    transaction as the status reset, so a reprocessed document never shows
    stale chunks.
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
        raise ReprocessNotAllowedError(
            "only failed or cancelled documents can be reprocessed"
        )
    await db.execute(_PURGE_CHUNKS, {"document_id": str(document_id)})
    return _serialize(row)


async def cancel_document(
    db: AsyncSession,
    identity: Identity,
    document_id: uuid.UUID,
) -> None:
    """Cancel a queued/processing document (docs/ingestion.md §1).

    Owner-only scoped: a foreign/missing id raises DocumentNotFoundError (404);
    anything not `uploaded`/`processing` raises CancelNotAllowedError (409).
    The status flip is the worker's stop signal: the pipeline polls between
    stages and aborts, so nothing persists for a cancelled document.
    """
    result = await db.execute(
        _CANCEL,
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
        raise CancelNotAllowedError(
            "only queued or processing documents can be cancelled"
        )


async def get_document_download_url(
    db: AsyncSession,
    storage: StorageProvider,
    identity: Identity,
    document_id: uuid.UUID,
    *,
    ttl_seconds: int,
) -> tuple[str, datetime]:
    """Mint a short-lived signed URL for one of the caller's documents.

    docs/api.md §5 (5 min), docs/multi-tenancy.md §4: objects are never public.
    Owner-only — a foreign or missing id raises DocumentNotFoundError (404,
    docs/security.md §2 anti-enumeration), so a caller can never learn another
    tenant's object key. Expiry is enforced by the issuing backend (Supabase
    validates `exp` server-side); the local provider is dev/CI-only and does
    not enforce expiry (documented risk, docs/security.md §7). A signing
    failure raises SignedUrlError (502) without leaking the storage path.
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


async def download_document(
    db: AsyncSession,
    storage: StorageProvider,
    identity: Identity,
    document_id: uuid.UUID,
) -> tuple[str, bytes]:
    """Stream one of the caller's documents as raw bytes (docs/api.md §5).

    Owner-only — a foreign/missing id raises DocumentNotFoundError (404,
    docs/security.md §2 anti-enumeration). A storage read failure maps to 502
    (DownloadError) without leaking the object path.
    """
    result = await db.execute(
        _GET_DOCUMENT,
        {"document_id": str(document_id), "user_id": str(identity.user_id)},
    )
    row = result.one_or_none()
    if row is None:
        raise DocumentNotFoundError("document not found")
    try:
        data = await storage.download(key=row.storage_path)
    except StorageError as exc:
        raise DownloadError("download failed") from exc
    return row.filename, data


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
