"""StorageProvider contract tests (contracts/storage.md, research.md R7/R8).

No database required. Covers key validation for both providers, the local
provider roundtrip, and the Supabase provider REST surface via httpx
MockTransport (endpoints, headers, relative signed-URL prefixing).
Async scenarios run with asyncio.run — same pattern as tests/test_auth_api.py.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import httpx
import pytest

from app.providers.storage import build_storage_provider
from app.providers.storage.base import StorageError, validate_key
from app.providers.storage.local import LocalStorageProvider
from app.providers.storage.supabase import SupabaseStorageProvider

USER = uuid.UUID("11111111-1111-1111-1111-111111111111")
KEY = f"{USER}/docs/{uuid.uuid4()}.pdf"


def test_validate_key_accepts_tenant_prefixed_key() -> None:
    validate_key(KEY, USER)


@pytest.mark.parametrize(
    "bad_key",
    [
        f"other-user/docs/{uuid.uuid4()}.pdf",
        f"docs/{uuid.uuid4()}.pdf",
        f"../{USER}/docs/x.pdf",
        f"{USER}/../docs/x.pdf",
        f"{USER}/docs/..//x.pdf",
        f"{USER}//docs/x.pdf",
        f"/{USER}/docs/x.pdf",
        f"{USER}\\docs\\x.pdf",
        f"{USER}/docs/x.pdf\x00",
    ],
)
def test_validate_key_rejects_unsafe_keys(bad_key: str) -> None:
    with pytest.raises(StorageError):
        validate_key(bad_key, USER)


def test_local_roundtrip_upload_download_delete(tmp_path: Path) -> None:
    provider = LocalStorageProvider(root=tmp_path)
    key = f"{USER}/docs/{uuid.uuid4()}.pdf"

    async def scenario() -> None:
        await provider.upload(
            key=key, data=b"%PDF-1.4 test", content_type="application/pdf"
        )
        assert await provider.download(key=key) == b"%PDF-1.4 test"
        object_path = tmp_path / key
        assert object_path.is_file()
        await provider.delete(key=key)
        assert not object_path.exists()
        await provider.delete(key=key)

    asyncio.run(scenario())


def test_local_rejects_key_without_tenant_prefix(tmp_path: Path) -> None:
    provider = LocalStorageProvider(root=tmp_path)
    no_prefix = "x.pdf"

    async def scenario() -> None:
        with pytest.raises(StorageError):
            await provider.upload(
                key=no_prefix, data=b"x", content_type="application/pdf"
            )

    asyncio.run(scenario())


def test_local_signed_url_is_file_uri(tmp_path: Path) -> None:
    provider = LocalStorageProvider(root=tmp_path)

    async def scenario() -> None:
        url = await provider.signed_url(key=KEY)
        assert url == (tmp_path / KEY).as_uri()

    asyncio.run(scenario())


class _SupabaseTransport(httpx.MockTransport):
    """Records the last request; returns canned storage responses."""

    def __init__(self, *, signed_url_path: str | None = None) -> None:
        self.last_request: httpx.Request | None = None
        self.signed_url_path = signed_url_path

        def handler(request: httpx.Request) -> httpx.Response:
            self.last_request = request
            if request.method == "POST" and "/sign/" in request.url.path:
                path = self.signed_url_path or (
                    f"/object/sign/{request.url.path.rsplit('/', 1)[-1]}"
                )
                return httpx.Response(200, json={"signedURL": path})
            if request.method == "GET":
                return httpx.Response(200, content=b"%PDF-1.4 downloaded")
            if request.method == "DELETE":
                return httpx.Response(200, json={"message": "Successfully deleted"})
            return httpx.Response(
                200,
                json={
                    "Key": "documents/" + request.url.path.rsplit("/", 1)[-1],
                    "Id": str(uuid.uuid4()),
                },
            )

        super().__init__(handler)


def _supabase_provider(transport: _SupabaseTransport) -> SupabaseStorageProvider:
    client = httpx.AsyncClient(
        transport=transport, base_url="https://proj.supabase.co/storage/v1"
    )
    return SupabaseStorageProvider(
        base_url="https://proj.supabase.co",
        service_role_key="service-role",
        bucket="documents",
        client=client,
    )


def test_supabase_upload_sends_service_role_headers() -> None:
    transport = _SupabaseTransport()
    provider = _supabase_provider(transport)

    async def scenario() -> None:
        await provider.upload(key=KEY, data=b"%PDF-1.4", content_type="application/pdf")

    asyncio.run(scenario())
    request = transport.last_request
    assert request is not None
    assert request.method == "POST"
    assert request.url.path == f"/storage/v1/object/documents/{KEY}"
    assert request.headers["apikey"] == "service-role"
    assert request.headers["authorization"] == "Bearer service-role"
    assert request.headers["content-type"] == "application/pdf"
    assert request.content == b"%PDF-1.4"


def test_supabase_download() -> None:
    transport = _SupabaseTransport()
    provider = _supabase_provider(transport)

    async def scenario() -> None:
        return await provider.download(key=KEY)

    data = asyncio.run(scenario())
    assert data == b"%PDF-1.4 downloaded"
    assert transport.last_request is not None
    assert transport.last_request.method == "GET"
    assert transport.last_request.url.path == f"/storage/v1/object/documents/{KEY}"


def test_supabase_delete_single_key() -> None:
    transport = _SupabaseTransport()
    provider = _supabase_provider(transport)

    asyncio.run(provider.delete(key=KEY))
    assert transport.last_request is not None
    assert transport.last_request.method == "DELETE"
    assert transport.last_request.url.path == f"/storage/v1/object/documents/{KEY}"


def test_supabase_signed_url_prefixes_relative_path() -> None:
    transport = _SupabaseTransport(signed_url_path="/object/sign/documents/x?token=abc")
    provider = _supabase_provider(transport)

    async def scenario() -> str:
        return await provider.signed_url(key=KEY, expires_in_seconds=300)

    url = asyncio.run(scenario())
    assert (
        url == "https://proj.supabase.co/storage/v1/object/sign/documents/x?token=abc"
    )
    request = transport.last_request
    assert request is not None
    assert request.url.path == f"/storage/v1/object/sign/documents/{KEY}"
    assert request.read() == b'{"expiresIn":300}'


def test_supabase_signed_url_passes_through_absolute() -> None:
    transport = _SupabaseTransport(
        signed_url_path="https://cdn.example.com/object/sign/x?token=abc"
    )
    provider = _supabase_provider(transport)

    async def scenario() -> str:
        return await provider.signed_url(key=KEY)

    assert asyncio.run(scenario()) == "https://cdn.example.com/object/sign/x?token=abc"


def test_supabase_rejects_key_without_tenant_prefix() -> None:
    transport = _SupabaseTransport()
    provider = _supabase_provider(transport)

    async def scenario() -> None:
        with pytest.raises(StorageError):
            await provider.upload(
                key="x.pdf", data=b"x", content_type="application/pdf"
            )

    asyncio.run(scenario())
    assert transport.last_request is None


class _FakeSettings:
    storage_provider = "local"
    local_storage_dir = "/data/storage"
    storage_bucket = "documents"
    supabase_url = ""
    supabase_service_role_key = ""


def test_factory_selects_local() -> None:
    provider = build_storage_provider(_FakeSettings())
    assert isinstance(provider, LocalStorageProvider)


def test_factory_selects_supabase() -> None:
    settings = _FakeSettings()
    settings.storage_provider = "supabase"
    settings.supabase_url = "https://proj.supabase.co"
    settings.supabase_service_role_key = "svc"
    provider = build_storage_provider(settings)
    assert isinstance(provider, SupabaseStorageProvider)


def test_factory_rejects_unknown_provider() -> None:
    settings = _FakeSettings()
    settings.storage_provider = "s3"
    with pytest.raises(ValueError, match="storage_provider"):
        build_storage_provider(settings)
