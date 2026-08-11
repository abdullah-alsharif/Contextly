"""LocalStorageProvider: flat file storage under LOCAL_STORAGE_DIR (dev/tests).

Zero credentials, no network (docs/local-dev.md §storage, contracts/storage.md §3).
Keys are tenant-prefixed ({user_id}/…, docs/multi-tenancy.md §4) and validated
through the shared validate_key before any I/O.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

from app.providers.storage.base import StorageError, validate_key


def _sync_upload(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with open(temp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _sync_download(path: Path) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except FileNotFoundError as exc:
        raise StorageError(f"object not found at {path}") from exc


def _sync_delete(path: Path) -> None:
    path.unlink(missing_ok=True)


class LocalStorageProvider:
    """Stores objects as files under `{root}/{user_id}/docs/{id}.pdf`.

    Writes are atomic (temp file + os.replace) so a crash never leaves a
    partial object at the final key (contracts/storage.md §3).
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _resolve(self, key: str, user_id: uuid.UUID | str) -> Path:
        validate_key(key, user_id)
        path = self.root / key
        if not path.is_relative_to(self.root):
            raise StorageError(f"key {key!r} escapes the storage root")
        return path

    async def upload(self, *, key: str, data: bytes, content_type: str) -> None:
        path = self._resolve(key, key.split("/", 1)[0])
        await asyncio.to_thread(_sync_upload, path, data)

    async def download(self, *, key: str) -> bytes:
        path = self._resolve(key, key.split("/", 1)[0])
        return await asyncio.to_thread(_sync_download, path)

    async def delete(self, *, key: str) -> None:
        path = self._resolve(key, key.split("/", 1)[0])
        await asyncio.to_thread(_sync_delete, path)

    async def signed_url(self, *, key: str, expires_in_seconds: int = 300) -> str:
        path = self._resolve(key, key.split("/", 1)[0])
        # Dev/CI-only (docs/security.md §7): a file:// URI has no signing or
        # expiry semantics — the `expires_in_seconds` parameter is accepted for
        # interface compatibility and ignored. Production expiry enforcement is
        # Supabase's signed token (`exp` validated server-side); the backends
        # that honor it are the ones the API documents (docs/multi-tenancy.md §4).
        return path.as_uri()
