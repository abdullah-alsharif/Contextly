"""Document API tests (quickstart VS-1..VS-5; docs/testing.md §1 documents group).

DB-gated: skipped when DATABASE_URL is unreachable (same pattern as test_auth_api.py).
Covers contracts/documents.md — upload validation matrix (201/400/413/401/502),
list/detail isolation (200/404/422), delete semantics (204/404), reprocess
(failed→uploaded round trip 200/400/404/401), cross-tenant 404s with owner data
intact. Storage is the local provider rooted in a tmp dir.
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


@pytest.fixture(autouse=True)
def clean_documents_before_each_test() -> None:
    """Independent per-test state (docs/testing.md §1 isolation).

    The Phase 12 dedupe policy (migration 0005) forbids two active rows with
    the same (user_id, filename), so rows left behind by an earlier test would
    409-collide with the next test's upload of the shared fixture name.
    """
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from documents where user_id in (%s, %s)",
                (str(USER_A), str(USER_B)),
            )
            cur.execute(
                "delete from action_logs where user_id in (%s, %s)",
                (str(USER_A), str(USER_B)),
            )
        conn.commit()
    yield


def _upload(
    client: TestClient,
    token: str,
    content: bytes = VALID_PDF,
    *,
    filename: str = "refund-policy.pdf",
    content_type: str = "application/pdf",
    replace: bool = False,
) -> tuple[int, dict]:
    params = "?replace=true" if replace else ""
    response = client.post(
        f"/api/v1/documents{params}",
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


def test_download_own_document_200(client: TestClient) -> None:
    token = _token(USER_A)
    _, doc = _upload(client, token, content=VALID_PDF)
    response = client.get(
        f"/api/v1/documents/{doc['id']}/download",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert 'inline; filename="refund-policy.pdf"' in response.headers[
        "content-disposition"
    ]
    assert response.content == VALID_PDF


def test_download_cross_tenant_404(client: TestClient) -> None:
    token_a, token_b = _token(USER_A), _token(USER_B)
    _, doc_a = _upload(client, token_a)
    response = client.get(
        f"/api/v1/documents/{doc_a['id']}/download",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 404


def test_download_storage_failure_502(client: TestClient) -> None:
    token = _token(USER_A)
    _, doc = _upload(client, token)
    app = client.app
    original = app.state.storage_provider
    app.state.storage_provider = _FailingStorage()
    try:
        response = client.get(
            f"/api/v1/documents/{doc['id']}/download",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 502
    finally:
        app.state.storage_provider = original


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


# ---------------------------------------------------------------------------
# Reprocess: PATCH /documents/{id}/reprocess
# ---------------------------------------------------------------------------
def test_reprocess_failed_round_trip_200(client: TestClient) -> None:
    """Reprocessing a failed doc resets it to 'uploaded', purges stale chunks,
    and the worker's next claim re-runs the pipeline to 'ready' (docs/ingestion.md
    §7: reprocess reuses the exact same worker)."""
    status, doc = _upload(client, _token(USER_A), content=make_pdf(["Retry content"]))
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
                "update documents set status = 'failed', status_error = 'boom', "
                "retry_count = 3, total_chunks = 2 where id = %s",
                (document_id,),
            )
        conn.commit()

    response = client.patch(
        f"/api/v1/documents/{document_id}/reprocess",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "uploaded"
    assert body["status_error"] is None
    assert body["total_chunks"] is None

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, retry_count from documents where id = %s",
                (document_id,),
            )
            assert cur.fetchone() == ("uploaded", 0)
            cur.execute(
                "select count(*) from document_chunks where document_id = %s",
                (document_id,),
            )
            assert cur.fetchone()[0] == 0

    asyncio.run(process())

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, total_chunks, status_error from documents where id = %s",
                (document_id,),
            )
            assert cur.fetchone() == ("ready", 1, None)


def test_reprocess_not_failed_400(client: TestClient) -> None:
    token = _token(USER_A)
    _, doc = _upload(client, token)
    response = client.patch(
        f"/api/v1/documents/{doc['id']}/reprocess",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400


def test_reprocess_cross_tenant_404(client: TestClient) -> None:
    token_a, token_b = _token(USER_A), _token(USER_B)
    _, doc_a = _upload(client, token_a)
    response = client.patch(
        f"/api/v1/documents/{doc_a['id']}/reprocess",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 404


def test_reprocess_nonexistent_404(client: TestClient) -> None:
    response = client.patch(
        f"/api/v1/documents/{uuid.uuid4()}/reprocess",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
    )
    assert response.status_code == 404


def test_reprocess_missing_auth_401(client: TestClient) -> None:
    assert (
        client.patch(f"/api/v1/documents/{uuid.uuid4()}/reprocess").status_code == 401
    )


# ---------------------------------------------------------------------------
# Cancel: POST /documents/{id}/cancel (Phase 12, docs/ingestion.md §1)
# ---------------------------------------------------------------------------
def test_cancel_queued_204(client: TestClient) -> None:
    """Cancelling an uploaded (queued) doc flips it to 'cancelled' immediately;
    it is never claimed by the worker and holds no chunks."""
    status, doc = _upload(client, _token(USER_A), content=make_pdf(["Queued content"]))
    assert status == 201
    document_id = uuid.UUID(doc["id"])

    response = client.post(
        f"/api/v1/documents/{document_id}/cancel",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
    )
    assert response.status_code == 204

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, lease_until from documents where id = %s",
                (document_id,),
            )
            status, lease_until = cur.fetchone()
            cur.execute(
                "select count(*) from document_chunks where document_id = %s",
                (document_id,),
            )
            chunk_count = cur.fetchone()[0]
    assert status == "cancelled"
    assert lease_until is None
    assert chunk_count == 0


def test_cancel_processing_204(client: TestClient) -> None:
    """Cancelling a claimed (processing) doc clears the lease and flips the
    status — the in-flight pipeline run aborts on its next poll."""
    status, doc = _upload(client, _token(USER_A), content=make_pdf(["Claimed content"]))
    assert status == 201
    document_id = uuid.UUID(doc["id"])

    async def claim() -> None:
        async with _TestSessionFactory() as db:
            claimed = await pipeline.claim_next(db, lease_seconds=300)
            assert claimed is not None and claimed.id == document_id
            await db.commit()

    asyncio.run(claim())

    response = client.post(
        f"/api/v1/documents/{document_id}/cancel",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
    )
    assert response.status_code == 204

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, lease_until from documents where id = %s",
                (document_id,),
            )
            status, lease_until = cur.fetchone()
    assert status == "cancelled"
    assert lease_until is None


def test_cancel_ready_409(client: TestClient) -> None:
    """A ready document is not cancellable — there is nothing to stop."""
    status, doc = _upload(client, _token(USER_A), content=make_pdf(["Ready content"]))
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

    response = client.post(
        f"/api/v1/documents/{document_id}/cancel",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
    )
    assert response.status_code == 409


def test_cancel_cross_tenant_404(client: TestClient) -> None:
    token_a, token_b = _token(USER_A), _token(USER_B)
    _, doc_a = _upload(client, token_a)
    response = client.post(
        f"/api/v1/documents/{doc_a['id']}/cancel",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 404


def test_cancel_nonexistent_404(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/documents/{uuid.uuid4()}/cancel",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
    )
    assert response.status_code == 404


def test_cancel_missing_auth_401(client: TestClient) -> None:
    assert (
        client.post(f"/api/v1/documents/{uuid.uuid4()}/cancel").status_code == 401
    )


def test_cancel_then_reprocess_round_trip_200(client: TestClient) -> None:
    """A cancelled doc can be reprocessed — the worker picks it up again."""
    status, doc = _upload(client, _token(USER_A), content=make_pdf(["Again?"]))
    assert status == 201
    document_id = uuid.UUID(doc["id"])

    response = client.post(
        f"/api/v1/documents/{document_id}/cancel",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
    )
    assert response.status_code == 204

    response = client.patch(
        f"/api/v1/documents/{document_id}/reprocess",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "uploaded"


def test_cancel_then_reupload_same_filename_201(client: TestClient) -> None:
    """A cancelled row no longer blocks the duplicate check — re-uploading the
    same file creates a fresh row and reprocesses it (docs/api.md §2)."""
    token = _token(USER_A)
    status, doc = _upload(client, token, filename="payroll.pdf")
    assert status == 201

    response = client.post(
        f"/api/v1/documents/{doc['id']}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 204

    status, _ = _upload(client, token, filename="payroll.pdf")
    assert status == 201


# ---------------------------------------------------------------------------
# Duplicate policy: 409 on repeat upload, ?replace=true supersedes (Phase 12)
# ---------------------------------------------------------------------------


def test_upload_duplicate_filename_409(client: TestClient) -> None:
    token = _token(USER_A)
    status, first = _upload(client, token, filename="payroll.pdf")
    assert status == 201

    status, body = _upload(client, token, filename="payroll.pdf")
    assert status == 409
    assert "already" in body["detail"]
    response = client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={
            "file": ("payroll.pdf", VALID_PDF, "application/pdf"),
        },
    )
    assert response.headers.get("X-Existing-Document-Id") == first["id"]


def test_upload_replace_supersedes_old_and_purges_chunks(client: TestClient) -> None:
    """US: replace upload → old row stays in the table as 'superseded' with its
    previous status remembered; the new upload is processed fresh; superseded
    (and deleted) rows never block a future upload of the same name
    (docs/ingestion.md §5, §7)."""
    token = _token(USER_A)
    status, first = _upload(client, token, filename="payroll.pdf")
    assert status == 201
    first_id = uuid.UUID(first["id"])

    status, second = _upload(client, token, filename="payroll.pdf", replace=True)
    assert status == 201
    assert second["id"] != first["id"]
    assert second["status"] == "uploaded"

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, superseded_from from documents where id = %s",
                (first_id,),
            )
            assert cur.fetchone() == ("superseded", "uploaded")

    # status filter sees it
    response = client.get(
        "/api/v1/documents?status=superseded",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert any(doc["id"] == first["id"] for doc in response.json())

    # the active replacement still owns the name...
    status, _ = _upload(client, token, filename="payroll.pdf")
    assert status == 409

    # ...and re-replacing supersedes the previous replacement in turn
    status, third = _upload(client, token, filename="payroll.pdf", replace=True)
    assert status == 201
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status from documents where id = %s",
                (uuid.UUID(second["id"]),),
            )
            assert cur.fetchone()[0] == "superseded"
    assert third["id"] != second["id"]


def test_upload_replace_delete_after_ready_restores_old(client: TestClient) -> None:
    """Replacing a fully-processed document: chunks are KEPT while the
    replacement processes and purged only when it reaches 'ready'. Deleting
    the finalized replacement then undoes the replace: the old row is
    re-queued and the worker rebuilds its chunks from the stored file
    (docs/ingestion.md §7, migration 0008)."""
    token = _token(USER_A)
    status, doc = _upload(client, token, filename="payroll.pdf", content=make_pdf(["Old content"]))
    assert status == 201
    document_id = uuid.UUID(doc["id"])

    async def process(document_id: uuid.UUID) -> None:
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

    asyncio.run(process(document_id))

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("select total_chunks from documents where id = %s", (document_id,))
            assert cur.fetchone()[0] == 1

    status, replacement = _upload(
        client, token, filename="payroll.pdf", replace=True, content=make_pdf(["New content"])
    )
    assert status == 201

    # outcome pending: old chunks stay, old status remembered
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, superseded_from from documents where id = %s",
                (document_id,),
            )
            assert cur.fetchone() == ("superseded", "ready")
            cur.execute(
                "select count(*) from document_chunks where document_id = %s",
                (document_id,),
            )
            assert cur.fetchone()[0] == 1

    # replacement reaches ready -> old finalized: superseded, chunks purged,
    # restore ticket kept
    asyncio.run(process(uuid.UUID(replacement["id"])))

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, superseded_from, total_chunks from documents where id = %s",
                (document_id,),
            )
            assert cur.fetchone() == ("superseded", "ready", None)
            cur.execute(
                "select count(*) from document_chunks where document_id = %s",
                (document_id,),
            )
            assert cur.fetchone()[0] == 0

    # deleting the finalized replacement re-queues the old version (migration 0008)
    assert client.delete(
        f"/api/v1/documents/{replacement['id']}",
        headers={"Authorization": f"Bearer {token}"},
    ).status_code == 204
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, superseded_from, total_chunks from documents where id = %s",
                (document_id,),
            )
            assert cur.fetchone() == ("uploaded", None, None)

    asyncio.run(process(document_id))

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, total_chunks from documents where id = %s",
                (document_id,),
            )
            assert cur.fetchone() == ("ready", 1)
            cur.execute(
                "select count(*) from document_chunks where document_id = %s",
                (document_id,),
            )
            assert cur.fetchone()[0] == 1


def test_upload_replace_failure_restores_old_status(client: TestClient) -> None:
    """When the replacement fails, the old document returns to its previous
    status with its chunks intact — never left behind as 'Outdated'
    (docs/ingestion.md §7)."""
    token = _token(USER_A)
    status, first = _upload(
        client, token, filename="payroll.pdf", content=make_pdf(["Keep me"])
    )
    assert status == 201
    first_id = uuid.UUID(first["id"])

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
            assert claimed is not None and claimed.id == first_id
            await db.commit()
        async with _TestSessionFactory() as db:
            outcome = await pipeline.process_claimed_document(
                db, storage, settings, claimed, ai
            )
            assert outcome == "ready"
            await db.commit()

    asyncio.run(process())

    status, replacement = _upload(client, token, filename="payroll.pdf", replace=True)
    assert status == 201

    # worker's terminal failure (docs/api.md §3): the resolution trigger runs
    # in the same transaction as this update
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update documents set status = 'failed', status_error = 'boom', "
                "retry_count = 0 where id = %s",
                (replacement["id"],),
            )
        conn.commit()

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, superseded_from, total_chunks from documents where id = %s",
                (first_id,),
            )
            assert cur.fetchone() == ("ready", None, 1)
            cur.execute(
                "select count(*) from document_chunks where document_id = %s",
                (first_id,),
            )
            assert cur.fetchone()[0] == 1
            # the failed attempt left the active set, so the name is held only
            # by the restored original again (active filename index, migration 0005)
            cur.execute(
                "select status, superseded_from from documents where id = %s",
                (replacement["id"],),
            )
            assert cur.fetchone() == ("superseded", "failed")


def test_upload_replace_deleted_replacement_restores_old(client: TestClient) -> None:
    """Deleting a not-yet-resolved replacement undoes the replace: the old
    document returns to its previous status with its chunks and chunk count
    intact (docs/ingestion.md §7)."""
    token = _token(USER_A)
    status, first = _upload(client, token, filename="payroll.pdf", content=make_pdf(["Keep me"]))
    assert status == 201
    first_id = uuid.UUID(first["id"])

    async def process(document_id: uuid.UUID) -> None:
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

    asyncio.run(process(first_id))

    status, replacement = _upload(client, token, filename="payroll.pdf", replace=True)
    assert status == 201

    assert client.delete(
        f"/api/v1/documents/{replacement['id']}",
        headers={"Authorization": f"Bearer {token}"},
    ).status_code == 204

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, superseded_from, total_chunks from documents where id = %s",
                (first_id,),
            )
            assert cur.fetchone() == ("ready", None, 1)
            cur.execute(
                "select count(*) from document_chunks where document_id = %s",
                (first_id,),
            )
            assert cur.fetchone()[0] == 1


def test_upload_replace_delete_chain_guard(client: TestClient) -> None:
    """In a replace chain (A <- B <- C), deleting an intermediate superseded
    version does NOT restore its predecessor while a newer active version
    holds the name (migration 0008 guard). Deleting the head restores nothing:
    the intermediate was itself deleted, so its storage object is gone."""
    token = _token(USER_A)

    async def process(document_id: uuid.UUID) -> None:
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

    def _rows(*ids: uuid.UUID) -> list[tuple[str, bool, int | None]]:
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                rows = []
                for document_id in ids:
                    cur.execute(
                        "select status, deleted_at is not null, total_chunks "
                        "from documents where id = %s",
                        (document_id,),
                    )
                    rows.append(cur.fetchone())
                return rows

    status, version_a = _upload(
        client, token, filename="payroll.pdf", content=make_pdf(["Chain A"])
    )
    assert status == 201
    version_a_id = uuid.UUID(version_a["id"])
    asyncio.run(process(version_a_id))

    status, version_b = _upload(
        client, token, filename="payroll.pdf", replace=True, content=make_pdf(["Chain B"])
    )
    assert status == 201
    version_b_id = uuid.UUID(version_b["id"])
    asyncio.run(process(version_b_id))

    status, version_c = _upload(
        client, token, filename="payroll.pdf", replace=True, content=make_pdf(["Chain C"])
    )
    assert status == 201
    version_c_id = uuid.UUID(version_c["id"])
    asyncio.run(process(version_c_id))

    # deleting the intermediate (B) does not restore A: C is the live version
    assert client.delete(
        f"/api/v1/documents/{version_b_id}",
        headers={"Authorization": f"Bearer {token}"},
    ).status_code == 204
    assert _rows(version_a_id, version_b_id, version_c_id) == [
        ("superseded", False, None),
        ("superseded", True, None),
        ("ready", False, 1),
    ]

    # deleting the head (C) restores nothing: B was itself deleted, so its
    # storage object is gone and the row is not resurrected
    assert client.delete(
        f"/api/v1/documents/{version_c_id}",
        headers={"Authorization": f"Bearer {token}"},
    ).status_code == 204
    assert _rows(version_a_id, version_b_id, version_c_id) == [
        ("superseded", False, None),
        ("superseded", True, None),
        ("ready", True, 1),
    ]


def test_upload_replace_with_storage_failure_keeps_old_active(client: TestClient) -> None:
    """The supersede runs in the upload transaction: a storage failure rolls
    back, so the old document stays active (never half-replaced)."""
    token = _token(USER_A)
    status, first = _upload(client, token, filename="payroll.pdf")
    assert status == 201

    app = client.app

    class _ReplaceFailingStorage:
        async def upload(self, *, key: str, data: bytes, content_type: str) -> None:
            raise StorageError("simulated storage outage")

        async def download(self, *, key: str) -> bytes:
            raise StorageError("simulated storage outage")

        async def delete(self, *, key: str) -> None:
            raise StorageError("simulated storage outage")

        async def signed_url(self, *, key: str, expires_in_seconds: int = 300) -> str:
            raise StorageError("simulated storage outage")

    original = app.state.storage_provider
    app.state.storage_provider = _ReplaceFailingStorage()
    try:
        status, body = _upload(client, token, filename="payroll.pdf", replace=True)
        assert status == 502
        assert "unavailable" in body["detail"]
    finally:
        app.state.storage_provider = original

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, total_chunks from documents where id = %s",
                (uuid.UUID(first["id"]),),
            )
            assert cur.fetchone() == ("uploaded", None)


def test_upload_replace_without_duplicate_201(client: TestClient) -> None:
    status, doc = _upload(client, _token(USER_A), filename="fresh.pdf", replace=True)
    assert status == 201
    assert doc["status"] == "uploaded"


def test_upload_cross_tenant_same_filename_201(client: TestClient) -> None:
    token_a, token_b = _token(USER_A), _token(USER_B)
    status_a, doc_a = _upload(client, token_a, filename="shared.pdf")
    status_b, doc_b = _upload(client, token_b, filename="shared.pdf")
    assert status_a == 201
    assert status_b == 201
    assert doc_a["id"] != doc_b["id"]


def test_upload_after_delete_same_filename_201(client: TestClient) -> None:
    token = _token(USER_A)
    _, doc = _upload(client, token, filename="once.pdf")
    assert client.delete(
        f"/api/v1/documents/{doc['id']}", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 204
    status, _ = _upload(client, token, filename="once.pdf")
    assert status == 201


# ---------------------------------------------------------------------------
# Action-log recording (US1): each API action produces exactly one row
# ---------------------------------------------------------------------------


def _log_rows(user: uuid.UUID) -> list[tuple[str, str, str]]:
    """(action_type, filename, outcome) rows for a user, oldest first."""
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select action_type, filename, outcome from action_logs "
                "where user_id = %s order by created_at, id",
                (str(user),),
            )
            return cur.fetchall()


def test_log_upload_records_one_row(client: TestClient) -> None:
    token = _token(USER_A)
    status, doc = _upload(client, token, filename="audit.pdf")
    assert status == 201
    assert _log_rows(USER_A) == [("upload", "audit.pdf", "succeeded")]

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select document_id from action_logs where user_id = %s",
                (str(USER_A),),
            )
            assert cur.fetchone()[0] == uuid.UUID(doc["id"])


def test_log_replace_records_replace_and_superseded(client: TestClient) -> None:
    token = _token(USER_A)
    assert _upload(client, token, filename="audit.pdf")[0] == 201
    status, doc = _upload(client, token, filename="audit.pdf", replace=True)
    assert status == 201
    assert _log_rows(USER_A) == [
        ("upload", "audit.pdf", "succeeded"),
        ("upload", "audit.pdf", "succeeded"),
        ("replace", "audit.pdf", "succeeded"),
        ("superseded", "audit.pdf", "succeeded"),
    ]
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select document_id from action_logs "
                "where user_id = %s and action_type = 'replace'",
                (str(USER_A),),
            )
            assert cur.fetchone()[0] == uuid.UUID(doc["id"])


def test_log_delete_records_one_row(client: TestClient) -> None:
    token = _token(USER_A)
    _, doc = _upload(client, token, filename="audit.pdf")
    assert client.delete(
        f"/api/v1/documents/{doc['id']}", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 204
    assert _log_rows(USER_A) == [
        ("upload", "audit.pdf", "succeeded"),
        ("delete", "audit.pdf", "succeeded"),
    ]


def test_log_cancel_records_one_row(client: TestClient) -> None:
    token = _token(USER_A)
    _, doc = _upload(client, token, filename="audit.pdf")
    response = client.post(
        f"/api/v1/documents/{doc['id']}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 204
    assert _log_rows(USER_A) == [
        ("upload", "audit.pdf", "succeeded"),
        ("cancel", "audit.pdf", "succeeded"),
    ]


def test_log_reprocess_records_one_row(client: TestClient) -> None:
    token = _token(USER_A)
    _, doc = _upload(client, token, filename="audit.pdf")
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update documents set status = 'failed', status_error = 'boom' "
                "where id = %s",
                (doc["id"],),
            )
        conn.commit()
    response = client.patch(
        f"/api/v1/documents/{doc['id']}/reprocess",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert _log_rows(USER_A) == [
        ("upload", "audit.pdf", "succeeded"),
        ("reprocess", "audit.pdf", "succeeded"),
    ]


def test_log_events_scoped_per_user(client: TestClient) -> None:
    token_a, token_b = _token(USER_A), _token(USER_B)
    assert _upload(client, token_a, filename="audit.pdf")[0] == 201
    assert _upload(client, token_b, filename="audit.pdf")[0] == 201
    assert len(_log_rows(USER_A)) == 1
    assert [row[0] for row in _log_rows(USER_A)] == ["upload"]
    assert [row[0] for row in _log_rows(USER_B)] == ["upload"]
