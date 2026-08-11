"""Conversations API tests (specs/008-chat-conversations, US1).

DB-gated (same DATABASE_URL guard as test_documents_api.py). Covers
contracts/chat.md §1 — POST/GET/GET{id}/PATCH/DELETE /api/v1/conversations:
CRUD flows, newest-first listing, detail with selected documents, full-replace
selection semantics, cross-tenant 404 matrix, selection rules (own + ready
only, unchanged selection on rejection), and 401/422 validation.
"""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.core.security.dev import dev_token
from app.db.session import get_db
from app.main import create_app
from app.providers.ai.fake import FakeProvider

DEV_SECRET = "contextly-dev-secret-0123456789abcdef"

USER_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

READY_DOC_A = uuid.UUID("33333333-3333-3333-3333-333333333333")
NOT_READY_DOC_A = uuid.UUID("44444444-4444-4444-4444-444444444444")
READY_DOC_B = uuid.UUID("55555555-5555-5555-5555-555555555555")

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


def _make_client(settings: Settings) -> TestClient:
    async def get_test_db():
        async with _TestSessionFactory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app = create_app(settings=settings, ai_provider=FakeProvider(embedding_dims=1024))
    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    settings = Settings(
        database_url=os.environ["DATABASE_URL"],
        auth_mode="dev",
        app_env="dev",
        dev_jwt_secret=DEV_SECRET,
        storage_provider="local",
        local_storage_dir=str(tmp_path_factory.mktemp("storage")),
    )
    with _make_client(settings) as c:
        yield c


def _seed_user(conn: psycopg.Connection, user: uuid.UUID) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "insert into auth.users (id) values (%s) on conflict do nothing",
            (user,),
        )
        cur.execute(
            "insert into profiles (id, email) values (%s, %s) on conflict do nothing",
            (user, f"{user}@example.com"),
        )
    conn.commit()


def _seed_document(
    conn: psycopg.Connection, *, doc_id: uuid.UUID, user: uuid.UUID, status: str
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into documents (id, user_id, filename, storage_path, status, file_size_bytes)
            values (%s, %s, %s, %s, %s, 100) on conflict do nothing
            """,
            (doc_id, user, f"{doc_id}.pdf", f"{user}/docs/{doc_id}.pdf", status),
        )
    conn.commit()


@pytest.fixture(scope="module")
def seeded() -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        _seed_user(conn, USER_A)
        _seed_user(conn, USER_B)
        _seed_document(conn, doc_id=READY_DOC_A, user=USER_A, status="ready")
        _seed_document(conn, doc_id=NOT_READY_DOC_A, user=USER_A, status="uploaded")
        _seed_document(conn, doc_id=READY_DOC_B, user=USER_B, status="ready")
    yield
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("delete from conversation_documents")
            cur.execute("delete from conversations")
            cur.execute(
                "delete from documents where user_id in (%s, %s)", (USER_A, USER_B)
            )
            cur.execute("delete from profiles where id in (%s, %s)", (USER_A, USER_B))
        conn.commit()


def _create(
    client: TestClient,
    token: str,
    *,
    title: str | None = None,
    document_ids: list[str] | None = None,
) -> tuple[int, dict]:
    body: dict = {}
    if title is not None:
        body["title"] = title
    if document_ids is not None:
        body["document_ids"] = document_ids
    response = client.post(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    return response.status_code, response.json() if response.content else {}


def _detail(client: TestClient, token: str, conv: str) -> tuple[int, dict]:
    response = client.get(
        f"/api/v1/conversations/{conv}", headers={"Authorization": f"Bearer {token}"}
    )
    return response.status_code, response.json() if response.content else {}


# ---------------------------------------------------------------------------
# CRUD flows
# ---------------------------------------------------------------------------


def test_create_with_title_and_documents(client: TestClient, seeded: None) -> None:
    status, body = _create(
        client, _token(USER_A), title="My docs", document_ids=[str(READY_DOC_A)]
    )
    assert status == 201
    assert body["title"] == "My docs"
    assert "id" in body and "created_at" in body and "updated_at" in body


def test_create_defaults_title_and_empty_selection(
    client: TestClient, seeded: None
) -> None:
    status, body = _create(client, _token(USER_A))
    assert status == 201
    assert body["title"] == "New conversation"


def test_list_is_newest_first_by_updated_at(client: TestClient, seeded: None) -> None:
    token = _token(USER_A)
    _, first = _create(client, token, title="older")
    _, second = _create(client, token, title="newer")
    response = client.get(
        "/api/v1/conversations", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    body = response.json()
    ids = [row["id"] for row in body]
    assert second["id"] in ids and first["id"] in ids
    assert ids.index(second["id"]) < ids.index(first["id"])  # newest first

    # PATCH bumps updated_at → reorders to the top.
    response = client.patch(
        f"/api/v1/conversations/{first['id']}",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "bumped"},
    )
    assert response.status_code == 200
    response = client.get(
        "/api/v1/conversations", headers={"Authorization": f"Bearer {token}"}
    )
    body = response.json()
    ids = [row["id"] for row in body]
    assert ids[0] == first["id"]


def test_detail_returns_selected_documents(client: TestClient, seeded: None) -> None:
    token = _token(USER_A)
    _, created = _create(client, token, document_ids=[str(READY_DOC_A)])
    status, body = _detail(client, token, created["id"])
    assert status == 200
    assert body["conversation"]["title"] == "New conversation"
    assert [doc["id"] for doc in body["documents"]] == [str(READY_DOC_A)]


def test_patch_renames_and_replaces_selection(client: TestClient, seeded: None) -> None:
    token = _token(USER_A)
    _, created = _create(client, token, document_ids=[str(READY_DOC_A)])
    conv = created["id"]

    response = client.patch(
        f"/api/v1/conversations/{conv}",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "Renamed"},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Renamed"

    # Full replace: drop READY_DOC_A, add nothing → empty selection.
    response = client.patch(
        f"/api/v1/conversations/{conv}",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_ids": []},
    )
    assert response.status_code == 200
    _, detail = _detail(client, token, conv)
    assert detail["documents"] == []


def test_delete_hides_conversation(client: TestClient, seeded: None) -> None:
    token = _token(USER_A)
    _, created = _create(client, token)
    response = client.delete(
        f"/api/v1/conversations/{created['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 204
    status, _ = _detail(client, token, created["id"])
    assert status == 404


# ---------------------------------------------------------------------------
# Ownership: cross-tenant behaves as 404 (docs/security.md §2)
# ---------------------------------------------------------------------------


def test_cross_tenant_operations_are_404(client: TestClient, seeded: None) -> None:
    token_a = _token(USER_A)
    token_b = _token(USER_B)
    _, created = _create(client, token_a, title="A's conversation")
    conv = created["id"]

    status, body = _detail(client, token_b, conv)
    assert status == 404
    assert "id" not in body or body["id"] != conv  # never reveals the object

    response = client.patch(
        f"/api/v1/conversations/{conv}",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"title": "hijack"},
    )
    assert response.status_code == 404

    response = client.delete(
        f"/api/v1/conversations/{conv}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 404

    # A still owns it — B's attempts changed nothing.
    status, body = _detail(client, token_a, conv)
    assert status == 200
    assert body["conversation"]["title"] == "A's conversation"


def test_missing_and_deleted_conversations_are_404(
    client: TestClient, seeded: None
) -> None:
    token = _token(USER_A)
    status, _ = _detail(client, token, str(uuid.uuid4()))
    assert status == 404


def test_list_excludes_other_users_conversations(
    client: TestClient, seeded: None
) -> None:
    token_a = _token(USER_A)
    token_b = _token(USER_B)
    _, created = _create(client, token_a, title="A's conversation")
    response = client.get(
        "/api/v1/conversations", headers={"Authorization": f"Bearer {token_b}"}
    )
    body = response.json()
    assert created["id"] not in [row["id"] for row in body]


# ---------------------------------------------------------------------------
# Selection rules: own + ready only (docs/chat.md §2)
# ---------------------------------------------------------------------------


def test_selecting_foreign_document_is_404(client: TestClient, seeded: None) -> None:
    status, _ = _create(client, _token(USER_A), document_ids=[str(READY_DOC_B)])
    assert status == 404


def test_selecting_not_ready_document_is_404(client: TestClient, seeded: None) -> None:
    status, _ = _create(client, _token(USER_A), document_ids=[str(NOT_READY_DOC_A)])
    assert status == 404


def test_failed_patch_leaves_selection_unchanged(
    client: TestClient, seeded: None
) -> None:
    token = _token(USER_A)
    _, created = _create(client, token, document_ids=[str(READY_DOC_A)])
    conv = created["id"]

    response = client.patch(
        f"/api/v1/conversations/{conv}",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_ids": [str(READY_DOC_B)]},
    )
    assert response.status_code == 404

    status, detail = _detail(client, token, conv)
    assert status == 200
    assert [doc["id"] for doc in detail["documents"]] == [str(READY_DOC_A)]


# ---------------------------------------------------------------------------
# Validation + auth
# ---------------------------------------------------------------------------


def test_malformed_bodies_are_422(client: TestClient, seeded: None) -> None:
    token = _token(USER_A)
    response = client.post(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
        json={"document_ids": ["not-a-uuid"]},
    )
    assert response.status_code == 422
    response = client.post(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "   "},
    )
    assert response.status_code == 422


def test_unauthenticated_requests_are_401(client: TestClient, seeded: None) -> None:
    response = client.get("/api/v1/conversations")
    assert response.status_code == 401
    response = client.post("/api/v1/conversations", json={"title": "x"})
    assert response.status_code == 401
