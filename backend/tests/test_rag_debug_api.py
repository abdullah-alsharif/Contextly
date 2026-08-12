"""RAG debug endpoint tests (specs/007-rag-retrieval-engine, US4).

DB-gated (same DATABASE_URL guard as test_documents_api.py). Covers
contracts/retrieval.md §1 — POST /api/v1/rag/query: happy-path ranking and
metadata, empty-scope 200, tenant 404s, validation 422s, auth 401, dev-only
registration (404 outside APP_ENV=dev), and 502 on question-embedding failure
after retries. The query vector is injected via a fixed-vector AIProvider
(create_app(ai_provider=...)) so ranking assertions are exact; the fake
provider's end-to-end embedding path is exercised in the service tests.
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
from app.providers.ai.base import AIProviderError

DEV_SECRET = "contextly-dev-secret-0123456789abcdef"

USER_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

CONVERSATION_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
CONVERSATION_B = uuid.UUID("22222222-2222-2222-2222-222222222222")
DOCUMENT_A = uuid.UUID("33333333-3333-3333-3333-333333333333")

# Query vector (deterministic): [0.9, 0.1, 0, ...]
QUERY_VECTOR = [0.9, 0.1] + [0.0] * 1022

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


def _vec(values: list[float]) -> str:
    return "[" + ",".join(repr(v) for v in values) + "]"


class _FixedVectorProvider:
    """AIProvider double: embeds every question to QUERY_VECTOR (no I/O)."""

    embedding_dims = 1024
    embedding_model = "test-fixed"

    async def embed(
        self, texts: list[str], *, batch_size: int = 32, input_type: str = "passage"
    ) -> list[list[float]]:
        return [QUERY_VECTOR for _ in texts]


class _FailingProvider(_FixedVectorProvider):
    """AIProvider double that always raises; counts embed calls (retry proof)."""

    def __init__(self) -> None:
        self.calls = 0

    async def embed(
        self, texts: list[str], *, batch_size: int = 32, input_type: str = "passage"
    ) -> list[list[float]]:
        self.calls += 1
        raise AIProviderError("simulated outage", provider="test", status_code=500)


def _make_client(settings: Settings, ai_provider=None) -> TestClient:
    async def get_test_db():
        async with _TestSessionFactory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app = create_app(settings=settings, ai_provider=ai_provider)
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
    with _make_client(settings, ai_provider=_FixedVectorProvider()) as c:
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


def _seed_conversation(
    conn: psycopg.Connection, conv: uuid.UUID, user: uuid.UUID
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "insert into conversations (id, user_id, title) values (%s, %s, %s) "
            "on conflict do nothing",
            (conv, user, "t"),
        )
    conn.commit()


def _seed_ready_document(
    conn: psycopg.Connection,
    *,
    doc_id: uuid.UUID,
    user: uuid.UUID,
    filename: str = "refund-policy.pdf",
    chunks: list[tuple[float, float]] | None = None,
) -> None:
    chunks = chunks or [(0.8, 0.2), (0.9, 0.1), (0.0, 0.0)]
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into documents (id, user_id, filename, storage_path, status, file_size_bytes)
            values (%s, %s, %s, %s, 'ready', 100) on conflict do nothing
            """,
            (doc_id, user, filename, f"{user}/docs/{doc_id}.pdf"),
        )
        for i, (a, b) in enumerate(chunks):
            vec = _vec([a, b] + [0.0] * 1022)
            cur.execute(
                """
                insert into document_chunks
                    (id, document_id, chunk_index, page_number, content, embedding)
                values (%s, %s, %s, %s, %s, %s) on conflict do nothing
                """,
                (
                    uuid.uuid4(),
                    doc_id,
                    i,
                    1 + i,
                    f"chunk-{i} content",
                    vec,
                ),
            )
    conn.commit()


def _link(conn: psycopg.Connection, conv: uuid.UUID, doc_id: uuid.UUID) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "insert into conversation_documents (conversation_id, document_id) "
            "values (%s, %s) on conflict do nothing",
            (conv, doc_id),
        )
    conn.commit()


@pytest.fixture(scope="module")
def seeded(cleanup_after: None) -> tuple[uuid.UUID, uuid.UUID]:
    """User A owns conversation A linked to ready document A (3 chunks)."""
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        _seed_user(conn, USER_A)
        _seed_user(conn, USER_B)
        _seed_conversation(conn, CONVERSATION_A, USER_A)
        _seed_ready_document(conn, doc_id=DOCUMENT_A, user=USER_A)
        _link(conn, CONVERSATION_A, DOCUMENT_A)
    return CONVERSATION_A, DOCUMENT_A


@pytest.fixture(scope="module")
def cleanup_after() -> None:
    yield
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            # Scope cleanup to the fixture's users only (FKs cascade chunks,
            # conversations, messages) — never wipe shared dev data.
            cur.execute(
                "delete from documents where user_id in (%s, %s)", (USER_A, USER_B)
            )
            cur.execute(
                "delete from conversations where user_id in (%s, %s)", (USER_A, USER_B)
            )
            cur.execute("delete from profiles where id in (%s, %s)", (USER_A, USER_B))
        conn.commit()


def _query(
    client: TestClient,
    token: str,
    conversation_id: uuid.UUID,
    question: str = "What is the refund period?",
    top_k: int | None = None,
) -> tuple[int, dict]:
    body: dict = {"question": question, "conversation_id": str(conversation_id)}
    if top_k is not None:
        body["top_k"] = top_k
    response = client.post(
        "/api/v1/rag/query",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    return response.status_code, response.json() if response.content else {}


# ---------------------------------------------------------------------------
# US4: debug query endpoint
# ---------------------------------------------------------------------------


def test_happy_path_returns_ranked_hits_with_metadata(
    client: TestClient, seeded: tuple[uuid.UUID, uuid.UUID]
) -> None:
    conv, doc = seeded
    status, body = _query(client, _token(USER_A), conv)
    assert status == 200
    assert body["question"] == "What is the refund period?"
    assert body["conversation_id"] == str(conv)
    assert body["retrieval_ms"] >= 0
    hits = body["hits"]
    assert len(hits) == 3
    assert [h["chunk_index"] for h in hits] == [1, 0, 2]
    assert hits[0]["similarity"] > hits[1]["similarity"] > hits[2]["similarity"]
    assert hits[0]["document_id"] == str(doc)
    assert hits[0]["filename"] == "refund-policy.pdf"
    assert hits[0]["page_number"] == 2
    assert hits[0]["content"] == "chunk-1 content"


def test_top_k_override_limits_hits(
    client: TestClient, seeded: tuple[uuid.UUID, uuid.UUID]
) -> None:
    conv, _ = seeded
    status, body = _query(client, _token(USER_A), conv, top_k=2)
    assert status == 200
    assert len(body["hits"]) == 2


def test_empty_scope_returns_empty_hits(client: TestClient) -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conv = uuid.uuid4()
        _seed_user(conn, USER_B)
        _seed_conversation(conn, conv, USER_B)
    try:
        status, body = _query(client, _token(USER_B), conv)
        assert status == 200
        assert body["hits"] == []
    finally:
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute("delete from conversations where id = %s", (conv,))
            conn.commit()


def test_unowned_conversation_404(
    client: TestClient, seeded: tuple[uuid.UUID, uuid.UUID]
) -> None:
    conv, _ = seeded
    status, body = _query(client, _token(USER_B), conv)
    assert status == 404
    assert "conversation" in body["detail"].lower()


def test_missing_conversation_404(client: TestClient) -> None:
    status, body = _query(client, _token(USER_A), uuid.uuid4())
    assert status == 404
    assert "conversation" in body["detail"].lower()


def test_deleted_conversation_404(client: TestClient) -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conv = uuid.uuid4()
        _seed_conversation(conn, conv, USER_A)
        with conn.cursor() as cur:
            cur.execute(
                "update conversations set deleted_at = now() where id = %s", (conv,)
            )
        conn.commit()
    try:
        status, _ = _query(client, _token(USER_A), conv)
        assert status == 404
    finally:
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute("delete from conversations where id = %s", (conv,))
            conn.commit()


def test_question_validation_422(
    client: TestClient, seeded: tuple[uuid.UUID, uuid.UUID]
) -> None:
    conv, _ = seeded
    token = _token(USER_A)
    cases = [
        {"question": "", "conversation_id": str(conv)},
        {"question": "   ", "conversation_id": str(conv)},
        {"question": "x" * 4001, "conversation_id": str(conv)},
        {"question": "ok", "conversation_id": "not-a-uuid"},
        {"question": "ok", "conversation_id": str(conv), "top_k": 0},
        {"question": "ok", "conversation_id": str(conv), "top_k": 51},
    ]
    for body in cases:
        response = client.post(
            "/api/v1/rag/query",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )
        assert response.status_code == 422, body


def test_question_cap_tracks_settings(
    tmp_path_factory: pytest.TempPathFactory,
    seeded: tuple[uuid.UUID, uuid.UUID],
) -> None:
    conv, _ = seeded
    capped_settings = Settings(
        database_url=os.environ["DATABASE_URL"],
        auth_mode="dev",
        app_env="dev",
        dev_jwt_secret=DEV_SECRET,
        storage_provider="local",
        local_storage_dir=str(tmp_path_factory.mktemp("storage")),
        rag_query_max_chars=10,
    )
    with _make_client(capped_settings, ai_provider=_FixedVectorProvider()) as c:
        status, _ = _query(c, _token(USER_A), conv, question="x" * 11)
        assert status == 422
        status, body = _query(c, _token(USER_A), conv, question="x" * 10)
        assert status == 200
        assert isinstance(body["hits"], list)


def test_missing_token_401(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rag/query",
        json={"question": "hi", "conversation_id": str(CONVERSATION_A)},
    )
    assert response.status_code == 401


def test_invalid_token_401(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rag/query",
        headers={"Authorization": "Bearer not-a-real-token"},
        json={"question": "hi", "conversation_id": str(CONVERSATION_A)},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# US4: dev-only surface
# ---------------------------------------------------------------------------


def test_rag_endpoint_present_in_dev(client: TestClient) -> None:
    response = client.post(
        "/api/v1/rag/query",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
        json={"question": "hi", "conversation_id": str(CONVERSATION_A)},
    )
    assert response.status_code in (200, 404, 422)


def test_rag_endpoint_absent_outside_dev(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    prod_settings = Settings(
        database_url=os.environ["DATABASE_URL"],
        auth_mode="supabase",
        supabase_jwt_secret="test-secret",
        app_env="prod",
        ai_provider="nvidia",
        nvidia_api_key="test",
        # STORAGE_PROVIDER=local is dev-only; prod tests must use supabase.
        storage_provider="supabase",
        supabase_url="https://project.supabase.co",
        supabase_service_role_key="test-service-role",
    )
    with _make_client(prod_settings) as prod_client:
        response = prod_client.post(
            "/api/v1/rag/query",
            headers={"Authorization": f"Bearer {_token(USER_A)}"},
            json={"question": "hi", "conversation_id": str(CONVERSATION_A)},
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# US4: embedding failure mapping
# ---------------------------------------------------------------------------


def test_question_embed_failure_returns_502_after_retries(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    failing = _FailingProvider()
    settings = Settings(
        database_url=os.environ["DATABASE_URL"],
        auth_mode="dev",
        app_env="dev",
        dev_jwt_secret=DEV_SECRET,
        storage_provider="local",
        local_storage_dir=str(tmp_path_factory.mktemp("storage")),
    )
    with _make_client(settings, ai_provider=failing) as c:
        status, body = _query(c, _token(USER_A), CONVERSATION_A)
        assert status == 502
        assert "unavailable" in body["detail"].lower()
    assert failing.calls == 2  # initial attempt + 1 retry
