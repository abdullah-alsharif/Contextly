"""Document API tests (quickstart VS-1..VS-5; docs/testing.md §1 documents group).

DB-gated: skipped when DATABASE_URL is unreachable (same pattern as test_auth_api.py).
Covers contracts/documents.md — upload validation matrix (201/400/413/401/502),
list/detail isolation (200/404/422), delete semantics (204/404), cross-tenant
404s with owner data intact. Storage is the local provider rooted in a tmp dir.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.security.dev import dev_token
from app.db.session import get_db
from app.main import create_app
from app.providers.storage.base import StorageError
from app.services import pipeline
from app.services.documents import sanitize_filename
from tests.pdf_fixtures import make_pdf

DEV_SECRET = "contextly-dev-secret-0123456789abcdef"
MAX_UPLOAD = 10 * 1024 * 1024

USER_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

VALID_PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"

# Test-only engine: the module-scoped TestClient owns its loop, and the app's
# module-level engine may hold asyncpg connections created on another loop by
# earlier test modules (test_auth_api). NullPool + a dependency override keep
# this module's requests on their own connections (test_auth_api.py:141
# precedent).
_TEST_ENGINE = create_async_engine(
    os.getenv("DATABASE_URL", "postgresql://localhost/contextly").replace(
        "postgresql://", "postgresql+asyncpg://", 1
    ),
    poolclass=NullPool,
)
_TestSessionFactory = async_sessionmaker(_TEST_ENGINE, expire_on_commit=False)


def _database_reachable() -> bool:
    url = os.getenv("DATABASE_URL")
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=1) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _database_reachable(), reason="DATABASE_URL not reachable"
)


def _token(user: uuid.UUID) -> str:
    return dev_token(user, secret=DEV_SECRET)


class _FailingStorage:
    async def upload(self, *, key: str, data: bytes, content_type: str) -> None:
        raise StorageError("simulated storage outage")

    async def download(self, *, key: str) -> bytes:
        raise StorageError("simulated storage outage")

    async def delete(self, *, key: str) -> None:
        raise StorageError("simulated storage outage")

    async def signed_url(self, *, key: str, expires_in_seconds: int = 300) -> str:
        raise StorageError("simulated storage outage")


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    storage_dir = tmp_path_factory.mktemp("storage")
    settings = Settings(
        database_url=os.environ["DATABASE_URL"],
        auth_mode="dev",
        app_env="dev",
        dev_jwt_secret=DEV_SECRET,
        storage_provider="local",
        local_storage_dir=str(storage_dir),
        upload_max_bytes=MAX_UPLOAD,
    )

    async def get_test_db():
        async with _TestSessionFactory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app = create_app(settings=settings)
    app.dependency_overrides[get_db] = get_test_db
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def cleanup() -> None:
    yield
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from documents where user_id in (%s, %s)", (USER_A, USER_B)
            )
            cur.execute("delete from profiles where id in (%s, %s)", (USER_A, USER_B))
        conn.commit()


def _upload(
    client: TestClient,
    token: str,
    content: bytes = VALID_PDF,
    *,
    filename: str = "refund-policy.pdf",
    content_type: str = "application/pdf",
) -> tuple[int, dict]:
    response = client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (filename, content, content_type)},
    )
    return response.status_code, response.json() if response.content else {}


# ---------------------------------------------------------------------------
# US1: upload
# ---------------------------------------------------------------------------


def test_upload_valid_pdf_201(client: TestClient, cleanup: None) -> None:
    status, body = _upload(client, _token(USER_A))
    assert status == 201
    assert body["status"] == "uploaded"
    assert body["filename"] == "refund-policy.pdf"
    assert body["file_size_bytes"] == len(VALID_PDF)
    assert body["total_chunks"] is None
    assert body["status_error"] is None

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, storage_path from documents where id = %s",
                (body["id"],),
            )
            row = cur.fetchone()
    assert row == ("uploaded", f"{USER_A}/docs/{body['id']}.pdf")


def test_upload_wrong_content_type_400(client: TestClient) -> None:
    status, body = _upload(
        client, _token(USER_A), content_type="text/plain", filename="notes.txt"
    )
    assert status == 400
    assert body["detail"]


def test_upload_wrong_extension_400(client: TestClient) -> None:
    status, _ = _upload(client, _token(USER_A), filename="refund-policy.txt")
    assert status == 400


def test_upload_missing_magic_bytes_400(client: TestClient) -> None:
    status, _ = _upload(client, _token(USER_A), content=b"not really a pdf")
    assert status == 400


def test_upload_empty_file_400(client: TestClient) -> None:
    status, _ = _upload(client, _token(USER_A), content=b"")
    assert status == 400


def test_upload_oversized_413(client: TestClient) -> None:
    big = b"%PDF-" + b"\0" * (MAX_UPLOAD + 1)
    status, body = _upload(client, _token(USER_A), content=big)
    assert status == 413
    assert body["detail"]


def test_upload_exactly_at_limit_201(client: TestClient) -> None:
    exact = b"%PDF-" + b"\0" * (MAX_UPLOAD - 5)
    assert len(exact) == MAX_UPLOAD
    status, body = _upload(client, _token(USER_A), content=exact)
    assert status == 201
    assert body["file_size_bytes"] == MAX_UPLOAD


def test_upload_missing_auth_401(client: TestClient) -> None:
    response = client.post(
        "/api/v1/documents", files={"file": ("x.pdf", VALID_PDF, "application/pdf")}
    )
    assert response.status_code == 401


def test_upload_storage_failure_502_no_row(client: TestClient) -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from documents where user_id = %s", (USER_A,))
            before = cur.fetchone()[0]

    app = client.app
    original = app.state.storage_provider
    app.state.storage_provider = _FailingStorage()
    try:
        status, body = _upload(client, _token(USER_A))
        assert status == 502
        assert body["detail"]
    finally:
        app.state.storage_provider = original

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from documents where user_id = %s", (USER_A,))
            assert cur.fetchone()[0] == before


def test_upload_sanitizes_filename(client: TestClient) -> None:
    status, body = _upload(
        client,
        _token(USER_A),
        filename="../../hidden/refundpolicy.pdf",
    )
    assert status == 201
    assert body["filename"] == "refundpolicy.pdf"


def test_sanitize_filename_strips_control_chars() -> None:
    assert sanitize_filename("../../hidden/refund\tpolicy.pdf") == "refundpolicy.pdf"
    assert sanitize_filename("C:\\evil\\payroll.pdf") == "payroll.pdf"


# ---------------------------------------------------------------------------
# US2: list + detail
# ---------------------------------------------------------------------------


def test_list_returns_only_own_documents(client: TestClient) -> None:
    token_a, token_b = _token(USER_A), _token(USER_B)
    status, doc_a = _upload(client, token_a)
    assert status == 201
    status, doc_b = _upload(client, token_b, filename="b-policy.pdf")
    assert status == 201

    response = client.get(
        "/api/v1/documents", headers={"Authorization": f"Bearer {token_a}"}
    )
    assert response.status_code == 200
    ids = [doc["id"] for doc in response.json()]
    assert doc_a["id"] in ids
    assert doc_b["id"] not in ids


def test_list_status_filter(client: TestClient) -> None:
    token = _token(USER_A)
    _upload(client, token)
    response = client.get(
        "/api/v1/documents?status=uploaded",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert all(doc["status"] == "uploaded" for doc in response.json())


def test_list_invalid_status_422(client: TestClient) -> None:
    response = client.get(
        "/api/v1/documents?status=banana",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
    )
    assert response.status_code == 422


def test_list_missing_auth_401(client: TestClient) -> None:
    assert client.get("/api/v1/documents").status_code == 401


def test_detail_own_document_200(client: TestClient) -> None:
    token = _token(USER_A)
    _, doc = _upload(client, token)
    response = client.get(
        f"/api/v1/documents/{doc['id']}", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["id"] == doc["id"]


def test_detail_cross_tenant_404(client: TestClient) -> None:
    token_a, token_b = _token(USER_A), _token(USER_B)
    _, doc_a = _upload(client, token_a)
    response = client.get(
        f"/api/v1/documents/{doc_a['id']}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 404


def test_detail_nonexistent_404(client: TestClient) -> None:
    response = client.get(
        f"/api/v1/documents/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
    )
    assert response.status_code == 404


def test_detail_missing_auth_401(client: TestClient) -> None:
    assert client.get(f"/api/v1/documents/{uuid.uuid4()}").status_code == 401


# ---------------------------------------------------------------------------
# US3: delete
# ---------------------------------------------------------------------------


def test_delete_own_document_204(client: TestClient) -> None:
    token = _token(USER_A)
    _, doc = _upload(client, token)
    response = client.delete(
        f"/api/v1/documents/{doc['id']}", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 204

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select deleted_at, storage_path from documents where id = %s",
                (doc["id"],),
            )
            deleted_at, storage_path = cur.fetchone()
    assert deleted_at is not None

    storage_dir = client.app.state.storage_provider.root  # type: ignore[attr-defined]
    assert not (storage_dir / storage_path).exists()

    response = client.get(
        f"/api/v1/documents/{doc['id']}", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404


def test_delete_again_404(client: TestClient) -> None:
    token = _token(USER_A)
    _, doc = _upload(client, token)
    client.delete(
        f"/api/v1/documents/{doc['id']}", headers={"Authorization": f"Bearer {token}"}
    )
    response = client.delete(
        f"/api/v1/documents/{doc['id']}", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404


def test_delete_cross_tenant_404_owner_intact(client: TestClient) -> None:
    token_a, token_b = _token(USER_A), _token(USER_B)
    _, doc_a = _upload(client, token_a)
    response = client.delete(
        f"/api/v1/documents/{doc_a['id']}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 404

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select deleted_at from documents where id = %s", (doc_a["id"],)
            )
            assert cur.fetchone()[0] is None

    storage_dir = client.app.state.storage_provider.root  # type: ignore[attr-defined]
    assert (storage_dir / f"{USER_A}/docs/{doc_a['id']}.pdf").exists()


def test_delete_nonexistent_404(client: TestClient) -> None:
    response = client.delete(
        f"/api/v1/documents/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
    )
    assert response.status_code == 404


def test_delete_missing_auth_401(client: TestClient) -> None:
    assert client.delete(f"/api/v1/documents/{uuid.uuid4()}").status_code == 401


def test_delete_purges_processed_chunks(client: TestClient) -> None:
    """US4: DELETE removes the chunks of an already-processed document (quickstart
    VS-6; docs/ingestion.md §7). Processing is driven through the Phase 4
    pipeline so the API path sees a fully-ready document."""
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from document_chunks where document_id in "
                "(select id from documents where user_id = any(%s))",
                ([str(USER_A), str(USER_B)],),
            )
            cur.execute(
                "delete from documents where user_id = any(%s)",
                ([str(USER_A), str(USER_B)],),
            )
        conn.commit()

    status, doc = _upload(
        client, _token(USER_A), content=make_pdf(["Deletable content"])
    )
    assert status == 201
    document_id = uuid.UUID(doc["id"])

    async def process() -> None:
        storage = client.app.state.storage_provider  # type: ignore[attr-defined]
        settings = Settings(
            database_url=os.environ["DATABASE_URL"],
            auth_mode="dev",
            app_env="dev",
        )
        from app.providers.ai import build_ai_provider

        ai = build_ai_provider(settings)
        async with _TestSessionFactory() as db:
            claimed = await pipeline.claim_next(db, lease_seconds=300)
            assert claimed is not None and claimed.id == document_id
            await db.commit()
        async with _TestSessionFactory() as db:
            outcome = await pipeline.process_claimed_document(
                db, storage, settings, claimed, ai
            )
            assert outcome == "ready"
            await db.commit()

    asyncio.run(process())

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select count(*) from document_chunks where document_id = %s",
                (document_id,),
            )
            assert cur.fetchone()[0] == 1

    response = client.delete(
        f"/api/v1/documents/{document_id}",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
    )
    assert response.status_code == 204

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select count(*) from document_chunks where document_id = %s",
                (document_id,),
            )
            assert cur.fetchone()[0] == 0
