"""StorageProvider abstraction: protocol, errors, and key validation.

Contract: specs/004-document-upload-storage/contracts/storage.md, following
docs/ai-providers.md §3. Every key is tenant-prefixed ({user_id}/…, docs/
multi-tenancy.md §4); both implementations MUST validate keys through the shared
validate_key helper — the provider boundary enforces the rule, never the caller.
"""

from __future__ import annotations

import re
import uuid
from typing import Protocol

_PREFIX_RE = re.compile(r"[\\\x00-\x1f\x7f]")


class StorageError(Exception):
    """Storage backend failure (vendor error, I/O error, invalid key)."""


class StorageProvider(Protocol):
    """Object-storage interface shared by local disk and Supabase Storage."""

    async def upload(self, *, key: str, data: bytes, content_type: str) -> None:
        """Store `data` at `key` with the given content type."""

    async def download(self, *, key: str) -> bytes:
        """Return the object bytes at `key`."""

    async def delete(self, *, key: str) -> None:
        """Remove the object at `key`; a missing object is not an error."""

    async def signed_url(self, *, key: str, expires_in_seconds: int = 300) -> str:
        """Short-lived access URL for `key` (docs/multi-tenancy.md §4)."""


def validate_key(key: str, user_id: uuid.UUID | str) -> None:
    """Reject keys that omit the tenant prefix or attempt path traversal.

    Security-critical (docs/ai-providers.md §3): called by every provider on
    every operation. Raises StorageError on any violation.
    """
    prefix = f"{user_id}/"
    if not key.startswith(prefix):
        raise StorageError(f"key {key!r} is missing the tenant prefix {prefix!r}")
    if key.startswith("/") or "\\" in key or "\x00" in key:
        raise StorageError(f"key {key!r} is not a relative object key")
    parts = key.split("/")
    if ".." in parts or "" in parts[1:]:
        raise StorageError(f"key {key!r} contains path traversal components")
