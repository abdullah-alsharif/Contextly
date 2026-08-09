"""SupabaseStorageProvider: thin httpx REST client for Supabase Storage.

Production implementation (contracts/storage.md §3, research.md R7). All calls
authenticate with the service-role key (apikey + Bearer) — service keys bypass
storage RLS entirely (research.md R6), so no storage.objects policies are
needed for this backend path. Endpoints (verified Aug 2026): upload
POST /object/{bucket}/{key}, download GET, delete DELETE (single-key form),
signed URL POST /object/sign/{bucket}/{key} (relative response must be
prefixed with the storage base URL).
"""
from __future__ import annotations

import httpx

from app.providers.storage.base import StorageError, validate_key

_MAX_EXPIRY_SECONDS = 604800


class SupabaseStorageProvider:
    """Supabase Storage client used by the backend with the service role.

    Keys are tenant-prefixed and validated through validate_key before any
    request (docs/multi-tenancy.md §4). No retries inside the provider this
    phase (contracts/storage.md §5); caller translates StorageError.
    """

    def __init__(
        self,
        *,
        base_url: str,
        service_role_key: str,
        bucket: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("SupabaseStorageProvider requires SUPABASE_URL")
        if not service_role_key:
            raise ValueError(
                "SupabaseStorageProvider requires SUPABASE_SERVICE_ROLE_KEY "
                "(STORAGE_PROVIDER=supabase is configured)"
            )
        if not bucket:
            raise ValueError("SupabaseStorageProvider requires a bucket name")
        self.bucket = bucket
        self._storage_base = f"{base_url.rstrip('/')}/storage/v1"
        self._service_role_key = service_role_key
        self._client = client or httpx.AsyncClient(base_url=self._storage_base)

    def _auth_headers(self) -> dict[str, str]:
        return {
            "apikey": self._service_role_key,
            "Authorization": f"Bearer {self._service_role_key}",
        }

    def _object_url(self, key: str) -> str:
        return f"/object/{self.bucket}/{key}"

    def _raise_for_status(self, response: httpx.Response, operation: str) -> None:
        if response.is_error:
            raise StorageError(
                f"supabase storage {operation} failed: "
                f"{response.status_code} {response.text[:200]}"
            )

    async def upload(self, *, key: str, data: bytes, content_type: str) -> None:
        validate_key(key, key.split("/", 1)[0])
        response = await self._client.post(
            self._object_url(key),
            content=data,
            headers={**self._auth_headers(), "Content-Type": content_type},
        )
        self._raise_for_status(response, "upload")

    async def download(self, *, key: str) -> bytes:
        validate_key(key, key.split("/", 1)[0])
        response = await self._client.get(self._object_url(key), headers=self._auth_headers())
        self._raise_for_status(response, "download")
        return response.content

    async def delete(self, *, key: str) -> None:
        validate_key(key, key.split("/", 1)[0])
        response = await self._client.delete(self._object_url(key), headers=self._auth_headers())
        self._raise_for_status(response, "delete")

    async def signed_url(self, *, key: str, expires_in_seconds: int = 300) -> str:
        validate_key(key, key.split("/", 1)[0])
        expires = max(1, min(expires_in_seconds, _MAX_EXPIRY_SECONDS))
        response = await self._client.post(
            f"/object/sign/{self.bucket}/{key}",
            json={"expiresIn": expires},
            headers=self._auth_headers(),
        )
        self._raise_for_status(response, "sign")
        signed_url: str = response.json().get("signedURL", "")
        if signed_url.startswith("http"):
            return signed_url
        return f"{self._storage_base}{signed_url}"

    async def aclose(self) -> None:
        await self._client.aclose()
