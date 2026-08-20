"""Documents router: POST/GET/GET{id}/DELETE /documents (docs/api.md §2).

Every endpoint resolves the caller via a get_current_user dependency, so
unauthenticated requests get 401 by construction (contracts/auth.md §1); the
general rate limit applies per route (docs/security.md §5). The download
endpoint uses `get_current_user_streaming` + an explicit `apply_identity_to_session`
on its own session: a request session would keep its profiles upsert locked
for the whole download stream (docs/chat.md §4). Error mapping: 400 invalid
upload, 413 oversized, 404 not owned/nonexistent/deleted, 502 upstream
storage failure (docs/api.md §2, §6).
"""

from __future__ import annotations

import io
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    enforce_general_rate_limit,
    enforce_general_rate_limit_streaming,
)
from app.core.config import Settings, get_settings
from app.core.security.deps import (
    apply_identity_to_session,
    get_current_user,
    get_current_user_streaming,
)
from app.core.security.identity import Identity
from app.db.session import get_db
from app.providers.storage.base import StorageProvider
from app.schemas.document import DocumentOut, DownloadUrlOut
from app.services.documents import (
    CancelNotAllowedError,
    DocumentNotFoundError,
    DownloadError,
    DuplicateDocumentError,
    InvalidUploadError,
    ReprocessNotAllowedError,
    SignedUrlError,
    UploadFailedError,
    UploadTooLargeError,
    cancel_document,
    create_document,
    delete_document,
    download_document,
    get_document,
    get_document_download_url,
    list_documents,
    reprocess_document,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/documents",
    tags=["documents"],
)


def get_storage_provider(request: Request) -> StorageProvider:
    """The app-scoped storage provider (injectable in tests via create_app)."""
    provider: StorageProvider = request.app.state.storage_provider
    return provider


async def _read_upload(file: UploadFile, settings: Settings) -> bytes:
    """Stream the upload in 1 MB chunks; enforce the size cap (docs/security.md §3)."""
    total = 0
    chunks: list[bytes] = []
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > settings.upload_max_bytes:
            raise UploadTooLargeError(
                f"file exceeds the {settings.upload_max_bytes} byte upload limit"
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("", response_model=DocumentOut, status_code=201, dependencies=[Depends(enforce_general_rate_limit)])
async def upload_document(
    file: UploadFile = File(...),
    replace: bool = False,
    identity: Identity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    storage: StorageProvider = Depends(get_storage_provider),
) -> dict[str, object]:
    """Upload a validated PDF and return the document with status 'uploaded'.

    Duplicate policy (docs/api.md §2): an active row with the same filename
    → 409 carrying the existing id in `X-Existing-Document-Id`. With
    `?replace=true` the old document is marked 'superseded' (chunks kept until
    the replacement resolves, docs/ingestion.md §7) and the new upload is
    processed normally.
    """
    try:
        data = await _read_upload(file, settings)
        return await create_document(
            db,
            storage,
            settings,
            identity,
            filename=file.filename or "",
            content_type=file.content_type or "",
            data=data,
            replace=replace,
        )
    except InvalidUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except DuplicateDocumentError as exc:
        headers = {}
        if exc.existing_id is not None:
            headers["X-Existing-Document-Id"] = str(exc.existing_id)
        raise HTTPException(status_code=409, detail=str(exc), headers=headers) from exc
    except UploadFailedError as exc:
        logger.error("upload failed for user %s: %s", identity.user_id, exc)
        raise HTTPException(
            status_code=502, detail="file storage is unavailable"
        ) from exc


@router.get("", response_model=list[DocumentOut], dependencies=[Depends(enforce_general_rate_limit)])
async def get_documents(
    status: Literal[
        "uploaded", "processing", "ready", "failed", "deleted", "superseded", "cancelled"
    ]
    | None = None,
    identity: Identity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, object]]:
    """List the caller's documents, newest first, optionally filtered by status."""
    return await list_documents(db, identity, status=status)


@router.get("/{document_id}", response_model=DocumentOut, dependencies=[Depends(enforce_general_rate_limit)])
async def get_document_detail(
    document_id: uuid.UUID,
    identity: Identity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Return one of the caller's documents; non-owned ids behave as 404."""
    try:
        return await get_document(db, identity, document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/{document_id}/download-url",
    response_model=DownloadUrlOut,
    dependencies=[Depends(enforce_general_rate_limit)],
)
async def get_download_url(
    document_id: uuid.UUID,
    identity: Identity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    storage: StorageProvider = Depends(get_storage_provider),
) -> dict[str, object]:
    """Mint a short-lived signed download URL (docs/api.md §5).

    Owner-only — a foreign/missing id behaves as 404 (docs/security.md §2
    anti-enumeration) and the storage provider is never asked to sign it.
    A storage signing failure maps to 502 without leaking the object path.
    """
    try:
        url, expires_at = await get_document_download_url(
            db,
            storage,
            identity,
            document_id,
            ttl_seconds=settings.storage_signed_url_ttl_seconds,
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SignedUrlError as exc:
        logger.error("signed URL failed for user %s: %s", identity.user_id, exc)
        raise HTTPException(
            status_code=502, detail="file storage is unavailable"
        ) from exc
    return {"url": url, "expires_at": expires_at}


@router.get(
    "/{document_id}/download",
    dependencies=[Depends(enforce_general_rate_limit_streaming)],
)
async def download_document_bytes(
    document_id: uuid.UUID,
    identity: Identity = Depends(get_current_user_streaming),
    db: AsyncSession = Depends(get_db),
    storage: StorageProvider = Depends(get_storage_provider),
) -> StreamingResponse:
    """Stream the document's PDF bytes inline (docs/api.md §5).

    Authenticated stream (Bearer token), so the frontend fetches the bytes via
    XHR and opens a blob URL — works for every storage provider instead of
    depending on browser-navigable signed URLs (a local file:// URI can't be
    opened from an http:// page). Owner-only 404, storage failure 502.
    """
    # RLS for this session: streaming auth holds no request session
    # (docs/chat.md §4), so the role + claim are applied here.
    await apply_identity_to_session(db, identity)
    try:
        filename, data = await download_document(db, storage, identity, document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DownloadError as exc:
        logger.error("download failed for user %s: %s", identity.user_id, exc)
        raise HTTPException(
            status_code=502, detail="file storage is unavailable"
        ) from exc
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.delete("/{document_id}", status_code=204, dependencies=[Depends(enforce_general_rate_limit)])
async def remove_document(
    document_id: uuid.UUID,
    identity: Identity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    storage: StorageProvider = Depends(get_storage_provider),
) -> None:
    """Soft-delete the document and remove its stored file (docs/ingestion.md §7)."""
    try:
        await delete_document(db, storage, identity, document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{document_id}/cancel", status_code=204, dependencies=[Depends(enforce_general_rate_limit)])
async def cancel_document_endpoint(
    document_id: uuid.UUID,
    identity: Identity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Cancel a queued/processing document (docs/ingestion.md §1); the worker
    aborts the in-flight run at its next stage poll."""
    try:
        await cancel_document(db, identity, document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CancelNotAllowedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch(
    "/{document_id}/reprocess",
    response_model=DocumentOut,
    dependencies=[Depends(enforce_general_rate_limit)],
)
async def reprocess_document_endpoint(
    document_id: uuid.UUID,
    identity: Identity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Re-queue a failed document: status → 'uploaded', chunks purged, so the
    worker re-runs parse → chunk → embed (docs/api.md §2, docs/ingestion.md §7)."""
    try:
        return await reprocess_document(db, identity, document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReprocessNotAllowedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
