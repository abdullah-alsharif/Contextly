"""Chat API tests: streaming send + history (specs/008-chat-conversations, US2).

DB-gated (same DATABASE_URL guard as test_conversations_api.py). Covers
contracts/chat.md §2-3 / docs/api.md §4 — POST/GET /conversations/{id}/messages:
SSE protocol (meta/delta/done), persisted messages with sources + metrics,
idempotent retries, history pagination (oldest first, X-Next-Cursor), and the
error matrix (404 foreign/missing, 400 no documents, 422 question cap, 401,
429 chat rate limit). Provider-failure persistence uses a deliberately
failing-stream provider (docs/chat.md §6).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.security.dev import dev_token
from app.db.session import get_db
from app.main import create_app
from app.providers.ai.base import AIProviderError
from app.providers.ai.fake import FakeProvider

from tests.test_conversations_api import (
    READY_DOC_A,
    USER_A,
    USER_B,
    _seed_document,
    _seed_user,
)

DEV_SECRET = "contextly-dev-secret-0123456789abcdef"
_READY_CHUNK_DOC_A = uuid.UUID("66666666-6666-6666-6666-666666666666")
_CONV_A = uuid.UUID("77777777-7777-7777-7777-777777777777")
_CONV_B = uuid.UUID("88888888-8888-8888-8888-888888888888")

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


def _make_client(
    settings: Settings, ai_provider: FakeProvider | None = None
) -> TestClient:
    async def get_test_db():
        async with _TestSessionFactory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app = create_app(
        settings=settings,
        ai_provider=ai_provider or FakeProvider(embedding_dims=1024),
        session_factory=_TestSessionFactory,
    )
    app.dependency_overrides[get_db] = get_test_db
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
        rate_limit_chat_per_minute=1000,  # shared client: keep tests limiter-agnostic
    )
    with _make_client(settings) as c:
        yield c


@pytest.fixture(scope="module")
def seeded() -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        _seed_user(conn, USER_A)
        _seed_user(conn, USER_B)
        _seed_document(conn, doc_id=READY_DOC_A, user=USER_A, status="ready")
        _seed_document(conn, doc_id=_READY_CHUNK_DOC_A, user=USER_A, status="ready")
        with conn.cursor() as cur:
            cur.execute(
                "insert into conversations (id, user_id, title) values (%s, %s, %s)",
                (_CONV_A, USER_A, "A's chat"),
            )
            cur.execute(
                "insert into conversations (id, user_id, title) values (%s, %s, %s)",
                (_CONV_B, USER_B, "B's chat"),
            )
            cur.execute(
                "insert into conversation_documents (conversation_id, document_id) "
                "values (%s, %s), (%s, %s)",
                (_CONV_A, _READY_CHUNK_DOC_A, _CONV_A, READY_DOC_A),
            )
            vector = "[" + ",".join(["0.01"] * 1024) + "]"
            cur.execute(
                "insert into document_chunks (document_id, chunk_index, content, "
                "page_number, token_count, embedding) values (%s, 0, %s, 4, 10, %s::vector)",
                (_READY_CHUNK_DOC_A, "The refund period is thirty days.", vector),
            )
    yield
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("delete from messages")
            cur.execute("delete from conversation_documents")
            cur.execute("delete from conversations")
            cur.execute("delete from document_chunks")
            cur.execute(
                "delete from documents where user_id in (%s, %s)", (USER_A, USER_B)
            )
            cur.execute("delete from profiles where id in (%s, %s)", (USER_A, USER_B))
        conn.commit()


def _create_conversation(
    client: TestClient, token: str, *, document_ids: list[str] | None = None
) -> dict:
    body: dict = {}
    if document_ids is not None:
        body["document_ids"] = document_ids
    response = client.post(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    assert response.status_code == 201
    return response.json()


def _send(
    client: TestClient,
    token: str,
    conversation_id: str,
    content: str,
    *,
    idempotency_key: str | None = None,
) -> tuple[int, list[tuple[str, dict]]]:
    headers = {"Authorization": f"Bearer {token}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": content},
    )
    if response.status_code != 200:
        return response.status_code, []
    events: list[tuple[str, dict]] = []
    for block in response.text.strip().split("\n\n"):
        lines = block.split("\n")
        event = "message"
        data = ""
        for line in lines:
            if line.startswith("event: "):
                event = line[len("event: ") :]
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        if data:
            events.append((event, __import__("json").loads(data)))
    return 200, events


def _history(
    client: TestClient, token: str, conversation_id: str, **params
) -> tuple[list[dict], str | None]:
    response = client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
    )
    assert response.status_code == 200
    return response.json(), response.headers.get("X-Next-Cursor")


class FailingStreamProvider(FakeProvider):
    """Streams one delta, then dies mid-stream (docs/chat.md §6)."""

    supports_streaming = True

    async def generate(
        self, messages: list[dict], *, stream: bool = False
    ) -> str | AsyncIterator[str]:
        async def _deltas() -> AsyncIterator[str]:
            yield "partial answer "
            raise AIProviderError("upstream blew up", provider="test")

        return _deltas()


class ExplodingStreamProvider(FakeProvider):
    """Streams one delta, then dies with an uncaught non-provider exception."""

    supports_streaming = True

    async def generate(
        self, messages: list[dict], *, stream: bool = False
    ) -> str | AsyncIterator[str]:
        async def _deltas() -> AsyncIterator[str]:
            yield "partial "
            raise RuntimeError("db blew up")

        return _deltas()


class FailOnceStreamProvider(FailingStreamProvider):
    """Fails mid-stream on the first call only, then streams the fake answer.

    Exercises the replay-after-failure path (spec US4/AC1): a `status='error'`
    partial must never shadow the later `done` answer in the replay lookup.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._calls = 0

    async def generate(
        self, messages: list[dict], *, stream: bool = False
    ) -> str | AsyncIterator[str]:
        self._calls += 1
        if self._calls == 1:
            return await super().generate(messages, stream=stream)
        return await FakeProvider.generate(self, messages, stream=stream)


# ---------------------------------------------------------------------------
# Send: SSE protocol
# ---------------------------------------------------------------------------


def test_send_streams_meta_deltas_done(client: TestClient, seeded: None) -> None:
    token = _token(USER_A)
    conv = _create_conversation(client, token, document_ids=[str(_READY_CHUNK_DOC_A)])
    status, events = _send(client, token, conv["id"], "What is the refund period?")
    assert status == 200
    names = [event for event, _ in events]
    assert names[0] == "meta"
    assert names[-1] == "done"
    assert "delta" in names
    full = "".join(data["text"] for event, data in events if event == "delta")
    assert "What is the refund period?" in full  # fake canned answer echoes question
    done = events[-1][1]
    assert done["sources"], "hits were expected: the doc has one embedded chunk"


def test_send_without_retrievable_chunks_returns_canned_answer(
    client: TestClient, seeded: None
) -> None:
    token = _token(USER_A)
    conv = _create_conversation(client, token, document_ids=[str(READY_DOC_A)])
    status, events = _send(client, token, conv["id"], "What is the refund period?")
    assert status == 200
    full = "".join(data["text"] for event, data in events if event == "delta")
    assert "No relevant documents found" in full  # docs/rag.md §7: no LLM call
    assert events[-1][1]["sources"] == []


def test_send_persists_messages_with_sources(client: TestClient, seeded: None) -> None:
    token = _token(USER_A)
    conv = _create_conversation(client, token, document_ids=[str(_READY_CHUNK_DOC_A)])
    status, events = _send(client, token, conv["id"], "What is the refund period?")
    assert status == 200
    done = events[-1][1]
    assert done["id"]
    assert done["sources"], "hits were expected: the doc has one embedded chunk"

    rows, _ = _history(client, token, conv["id"])
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert rows[0]["content"] == "What is the refund period?"
    assert rows[0]["status"] == "done"
    assert rows[1]["content"]
    assert rows[1]["sources"][0]["document_id"] == str(_READY_CHUNK_DOC_A)
    assert rows[1]["sources"][0]["filename"].endswith(".pdf")
    assert rows[1]["status"] == "done"
    assert rows[1]["retrieval_ms"] is not None
    assert rows[1]["llm_ms"] is not None


def test_sources_snapshot_survives_document_deletion(
    client: TestClient, seeded: None
) -> None:
    token = _token(USER_A)
    doomed_doc = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        _seed_document(conn, doc_id=doomed_doc, user=USER_A, status="ready")
        with conn.cursor() as cur:
            vector = "[" + ",".join(["0.01"] * 1024) + "]"
            cur.execute(
                "insert into document_chunks (document_id, chunk_index, content, "
                "page_number, token_count, embedding) values (%s, 0, %s, 4, 10, %s::vector)",
                (doomed_doc, "The refund period is thirty days.", vector),
            )
        conn.commit()

    conv = _create_conversation(client, token, document_ids=[str(doomed_doc)])
    status, events = _send(client, token, conv["id"], "What is the refund period?")
    assert status == 200
    done = events[-1][1]
    assert done["sources"], "hits were expected: the doc has one embedded chunk"
    source = done["sources"][0]
    assert source["document_id"] == str(doomed_doc)

    # SC-004: citations must survive later document deletion (docs/rag.md §5).
    response = client.delete(
        f"/api/v1/documents/{doomed_doc}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 204

    rows, _ = _history(client, token, conv["id"])
    assistant = [row for row in rows if row["role"] == "assistant"][0]
    assert assistant["sources"] == [source]  # stored snapshot, not read live


def test_send_auto_renames_default_title(client: TestClient, seeded: None) -> None:
    token = _token(USER_A)
    conv = _create_conversation(client, token, document_ids=[str(READY_DOC_A)])
    assert conv["title"] == "New conversation"
    status, _ = _send(client, token, conv["id"], "Tell me about refunds please")
    assert status == 200
    response = client.get(
        f"/api/v1/conversations/{conv['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    renamed = response.json()["conversation"]["title"]
    assert renamed == "Tell me about refunds please"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_same_idempotency_key_replays_answer(client: TestClient, seeded: None) -> None:
    token = _token(USER_A)
    conv = _create_conversation(client, token, document_ids=[str(READY_DOC_A)])
    key = str(uuid.uuid4())
    _, first = _send(client, token, conv["id"], "question one", idempotency_key=key)
    _, second = _send(client, token, conv["id"], "question one", idempotency_key=key)

    assert (
        first[0][0] == "meta"
        and first[0][1]["message_id"] == second[0][1]["message_id"]
    )
    assert [name for name, _ in second] == ["meta", "delta", "done"]
    replayed = "".join(d["text"] for n, d in second if n == "delta")
    original = "".join(d["text"] for n, d in first if n == "delta")
    assert replayed == original  # full answer replayed in one delta

    rows, _ = _history(client, token, conv["id"])
    user_rows = [row for row in rows if row["role"] == "user"]
    assert len(user_rows) == 1  # deduped, not duplicated


def test_inflight_idempotency_key_is_409(client: TestClient, seeded: None) -> None:
    token = _token(USER_A)
    key = "still-streaming-key"
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute(
            "insert into messages "
            "(conversation_id, role, content, idempotency_key) "
            "values (%s, 'user', %s, %s) on conflict do nothing",
            (_CONV_A, "seeded question", key),
        )
        conn.commit()
    assert client.app.state.chat_in_flight.mark(str(_CONV_A), key)

    response = client.post(
        f"/api/v1/conversations/{_CONV_A}/messages",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": key,
        },
        json={"content": "seeded question"},
    )
    assert response.status_code == 409  # contracts/chat.md §3: still streaming


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


def test_history_is_oldest_first_and_paginates(
    client: TestClient, seeded: None
) -> None:
    token = _token(USER_A)
    conv = _create_conversation(client, token, document_ids=[str(_READY_CHUNK_DOC_A)])
    status, _ = _send(client, token, conv["id"], "first question")
    assert status == 200
    status, _ = _send(client, token, conv["id"], "second question")
    assert status == 200

    page, next_cursor = _history(client, token, conv["id"], limit=2)
    assert [row["content"] for row in page] == [
        "second question",
        'Answer for "second question": Based on your documents, the answer is '
        "clear and can be cited from the retrieved excerpts.\n\n[1]",
    ]  # newest messages first; within a page oldest first
    assert next_cursor is not None  # more pages exist

    rest, next_cursor2 = _history(
        client, token, conv["id"], limit=2, cursor=next_cursor
    )
    assert [row["content"] for row in rest] == [
        "first question",
        'Answer for "first question": Based on your documents, the answer is '
        "clear and can be cited from the retrieved excerpts.\n\n[1]",
    ]
    assert next_cursor2 is None


def test_history_limit_100_returns_more_than_one_page(
    client: TestClient, seeded: None
) -> None:
    token = _token(USER_A)
    conv = _create_conversation(client, token, document_ids=[str(READY_DOC_A)])
    for index in range(30):
        status, _ = _send(client, token, conv["id"], f"bulk question {index}")
        assert status == 200

    rows, _ = _history(client, token, conv["id"], limit=100)
    assert len(rows) == 60  # 30 sends → 60 messages; limit=100 must not clamp to 50


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_send_to_conversation_without_documents_is_400(
    client: TestClient, seeded: None
) -> None:
    token = _token(USER_A)
    conv = _create_conversation(client, token)
    status, _ = _send(client, token, conv["id"], "hello?")
    assert status == 400


def test_send_to_foreign_or_missing_conversation_is_404(
    client: TestClient, seeded: None
) -> None:
    token_b = _token(USER_B)
    status, _ = _send(client, token_b, str(_CONV_A), "sneaky")
    assert status == 404
    status, _ = _send(client, token_b, str(uuid.uuid4()), "sneaky")
    assert status == 404


def test_history_of_foreign_conversation_is_404(
    client: TestClient, seeded: None
) -> None:
    response = client.get(
        f"/api/v1/conversations/{_CONV_A}/messages",
        headers={"Authorization": f"Bearer {_token(USER_B)}"},
    )
    assert response.status_code == 404


def test_history_limit_out_of_bounds_is_422(client: TestClient, seeded: None) -> None:
    token = _token(USER_A)
    headers = {"Authorization": f"Bearer {token}"}
    for bad_limit in (0, -1, 101):
        response = client.get(
            f"/api/v1/conversations/{_CONV_A}/messages",
            headers=headers,
            params={"limit": bad_limit},
        )
        assert response.status_code == 422  # contracts/chat.md §5: 1..100
    response = client.get(
        f"/api/v1/conversations/{_CONV_A}/messages",
        headers=headers,
        params={"limit": 100},
    )
    assert response.status_code == 200


def test_question_over_cap_is_422(client: TestClient, seeded: None) -> None:
    token = _token(USER_A)
    status, _ = _send(client, token, str(_CONV_A), "x" * 4001)
    assert status == 422
    status, _ = _send(client, token, str(_CONV_A), "   ")
    assert status == 422


def test_unauthenticated_send_is_401(client: TestClient, seeded: None) -> None:
    response = client.post(
        f"/api/v1/conversations/{_CONV_A}/messages", json={"content": "x"}
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Provider failures (docs/chat.md §6)
# ---------------------------------------------------------------------------


def test_midstream_failure_persists_error_status(
    seeded: None,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    settings = Settings(
        database_url=os.environ["DATABASE_URL"],
        auth_mode="dev",
        app_env="dev",
        dev_jwt_secret=DEV_SECRET,
        storage_provider="local",
        local_storage_dir=str(tmp_path_factory.mktemp("storage")),
    )
    with _make_client(
        settings, ai_provider=FailingStreamProvider(embedding_dims=1024)
    ) as c:
        token = _token(USER_A)
        conv = _create_conversation(c, token, document_ids=[str(_READY_CHUNK_DOC_A)])
        status, events = _send(c, token, conv["id"], "What is the refund period?")
        assert status == 200
        names = [name for name, _ in events]
        assert names[-1] == "error"
        rows, _ = _history(c, token, conv["id"])
        assistant = [row for row in rows if row["role"] == "assistant"][0]
        assert assistant["content"] == "partial answer "  # partial text persisted
        assert assistant["status"] == "error"  # UI shows a retry affordance


def test_replay_after_midstream_failure_uses_newest_done_answer(
    seeded: None,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """A failed attempt's `error` partial must not shadow the retried `done`
    answer: further replays reuse it instead of stacking new assistants.

    spec US4/AC1 (no duplicate messages), FR-014.
    """
    settings = Settings(
        database_url=os.environ["DATABASE_URL"],
        auth_mode="dev",
        app_env="dev",
        dev_jwt_secret=DEV_SECRET,
        storage_provider="local",
        local_storage_dir=str(tmp_path_factory.mktemp("storage")),
    )
    with _make_client(
        settings, ai_provider=FailOnceStreamProvider(embedding_dims=1024)
    ) as c:
        token = _token(USER_A)
        conv = _create_conversation(c, token, document_ids=[str(_READY_CHUNK_DOC_A)])
        key = str(uuid.uuid4())

        # Attempt 1: provider dies mid-stream → error event + partial error row.
        status, events = _send(
            c, token, conv["id"], "What is the refund period?", idempotency_key=key
        )
        assert status == 200
        assert events[-1][0] == "error"
        rows, _ = _history(c, token, conv["id"])
        failed = [row for row in rows if row["role"] == "assistant"][0]
        assert failed["status"] == "error"

        # Attempt 2: same key, provider works → new done answer.
        status, retry = _send(
            c, token, conv["id"], "What is the refund period?", idempotency_key=key
        )
        assert status == 200
        assert retry[-1][0] == "done"
        retry_done = retry[-1][1]

        # Attempt 3: same key again → replays attempt 2, no third assistant.
        status, replay = _send(
            c, token, conv["id"], "What is the refund period?", idempotency_key=key
        )
        assert status == 200
        assert [name for name, _ in replay] == ["meta", "delta", "done"]
        replayed = "".join(d["text"] for n, d in replay if n == "delta")
        original = "".join(d["text"] for n, d in retry if n == "delta")
        assert replayed == original  # stored answer replayed, not regenerated
        assert replay[-1][1]["id"] == retry_done["id"]

        rows, _ = _history(c, token, conv["id"])
        assistants = [row for row in rows if row["role"] == "assistant"]
        assert [row["status"] for row in assistants] == ["error", "done"]  # no 3rd
        assert assistants[-1]["id"] == retry_done["id"]


def test_unexpected_midstream_exception_yields_terminal_error(
    seeded: None,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    settings = Settings(
        database_url=os.environ["DATABASE_URL"],
        auth_mode="dev",
        app_env="dev",
        dev_jwt_secret=DEV_SECRET,
        storage_provider="local",
        local_storage_dir=str(tmp_path_factory.mktemp("storage")),
    )
    with _make_client(
        settings, ai_provider=ExplodingStreamProvider(embedding_dims=1024)
    ) as c:
        token = _token(USER_A)
        conv = _create_conversation(c, token, document_ids=[str(_READY_CHUNK_DOC_A)])
        status, events = _send(c, token, conv["id"], "What is the refund period?")
        assert status == 200
        names = [name for name, _ in events]
        assert names[-1] == "error"  # terminal error event, not a truncated stream
        rows, _ = _history(c, token, conv["id"])
        # nothing persisted on an unexpected failure: only the user row remains
        assert [row["role"] for row in rows] == ["user"]


# ---------------------------------------------------------------------------
# Rate limiting (docs/security.md §5)
# ---------------------------------------------------------------------------


def test_chat_rate_limit_returns_429(
    seeded: None,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    settings = Settings(
        database_url=os.environ["DATABASE_URL"],
        auth_mode="dev",
        app_env="dev",
        dev_jwt_secret=DEV_SECRET,
        storage_provider="local",
        local_storage_dir=str(tmp_path_factory.mktemp("storage")),
        rate_limit_chat_per_minute=2,
    )
    with _make_client(settings) as c:
        token = _token(USER_A)
        response = c.post(
            f"/api/v1/conversations/{_CONV_A}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"content": "one"},
        )
        assert response.status_code == 200
        response = c.post(
            f"/api/v1/conversations/{_CONV_A}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"content": "two"},
        )
        assert response.status_code == 200
        response = c.post(
            f"/api/v1/conversations/{_CONV_A}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"content": "three"},
        )
        assert response.status_code == 429
        assert "Retry-After" in response.headers


def test_history_respects_rate_limit(
    seeded: None,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    settings = Settings(
        database_url=os.environ["DATABASE_URL"],
        auth_mode="dev",
        app_env="dev",
        dev_jwt_secret=DEV_SECRET,
        storage_provider="local",
        local_storage_dir=str(tmp_path_factory.mktemp("storage")),
        rate_limit_chat_per_minute=2,
    )
    with _make_client(settings) as c:
        token = _token(USER_A)
        headers = {"Authorization": f"Bearer {token}"}
        for _ in range(2):
            response = c.get(
                f"/api/v1/conversations/{_CONV_A}/messages", headers=headers
            )
            assert response.status_code == 200
        response = c.get(f"/api/v1/conversations/{_CONV_A}/messages", headers=headers)
        assert response.status_code == 429  # GET history shares the chat budget
