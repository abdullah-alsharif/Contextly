"""Chat service tests (T016): pipeline internals at the service boundary.

Unit + integration coverage for `app.services.chat` beyond the HTTP layer
(specs/008-chat-conversations/tasks.md T016): context construction (numbered
[n] excerpts, docs/rag.md §4-5), protocol order, non-streaming fallback,
pre-stream commit semantics, idempotent replay, in-flight dedupe (409), and
the no-qualifying-chunks path (docs/rag.md §7).
"""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.dependencies import InFlightRegistry
from app.core.config import Settings
from app.core.security.identity import Identity
from app.providers.ai.base import AIProviderError
from app.providers.ai.fake import FakeProvider
from app.services.retrieval import RetrievalHit
from app.services.chat import (
    IdempotencyInFlightError,
    _NO_RELEVANT_ANSWER,
    _build_prompt_messages,
    prepare_chat,
    stream_chat_events,
)

DEV_SECRET = "contextly-dev-secret-0123456789abcdef"

SVC_USER = uuid.UUID("99999999-9999-9999-9999-999999999991")
SVC_CONV = uuid.UUID("99999999-9999-9999-9999-999999999992")
SVC_CONV_EMPTY = uuid.UUID("99999999-9999-9999-9999-999999999993")
SVC_DOC_CHUNKED = uuid.UUID("99999999-9999-9999-9999-999999999994")
SVC_DOC_EMPTY = uuid.UUID("99999999-9999-9999-9999-999999999995")

_SETTINGS = Settings(
    database_url=os.getenv("DATABASE_URL", "postgresql://localhost/contextly"),
    auth_mode="dev",
    app_env="dev",
    dev_jwt_secret=DEV_SECRET,
    retrieval_top_k=6,
    retrieval_ef_search=40,
)

_TEST_ENGINE = create_async_engine(
    _SETTINGS.database_url.replace("postgresql://", "postgresql+asyncpg://", 1),
    poolclass=NullPool,
)
_SessionFactory = async_sessionmaker(_TEST_ENGINE, expire_on_commit=False)

IDENTITY = Identity(user_id=SVC_USER)
AI = FakeProvider(embedding_dims=1024)


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


def _admin() -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"])


def _seed_user(user_id: uuid.UUID) -> None:
    with _admin() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into auth.users (id) values (%s) on conflict (id) do nothing",
                (user_id,),
            )
            cur.execute(
                "insert into profiles (id, email) values (%s, %s) "
                "on conflict (id) do nothing",
                (user_id, f"{user_id}@example.com"),
            )
        conn.commit()


def _seed_document(
    document_id: uuid.UUID, *, status: str = "ready", filename: str | None = None
) -> None:
    with _admin() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into documents "
                "(id, user_id, filename, storage_path, file_size_bytes, status, total_chunks) "
                "values (%s, %s, %s, %s, 100, %s, 1)",
                (
                    document_id,
                    SVC_USER,
                    filename or f"{document_id}.pdf",
                    f"{SVC_USER}/docs/{document_id}.pdf",
                    status,
                ),
            )
        conn.commit()


def _seed_chunk(document_id: uuid.UUID, *, content: str) -> None:
    vector = "[" + ",".join(["0.01"] * 1024) + "]"
    with _admin() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into document_chunks (document_id, chunk_index, content, "
                "page_number, token_count, embedding) values (%s, 0, %s, 4, 10, %s::vector)",
                (document_id, content, vector),
            )
        conn.commit()


def _seed_conversation(
    conversation_id: uuid.UUID, *, documents: list[uuid.UUID]
) -> None:
    with _admin() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into conversations (id, user_id, title) values (%s, %s, %s)",
                (conversation_id, SVC_USER, "SVC chat"),
            )
            for document_id in documents:
                cur.execute(
                    "insert into conversation_documents (conversation_id, document_id) "
                    "values (%s, %s)",
                    (conversation_id, document_id),
                )
        conn.commit()


@pytest.fixture(scope="module", autouse=True)
def seeded() -> None:
    _seed_user(SVC_USER)
    _seed_document(SVC_DOC_CHUNKED, filename="refund-policy.pdf")
    _seed_chunk(
        SVC_DOC_CHUNKED, content="The refund period is thirty days after purchase."
    )
    _seed_document(SVC_DOC_EMPTY, filename="empty.pdf")
    _seed_conversation(SVC_CONV, documents=[SVC_DOC_CHUNKED, SVC_DOC_EMPTY])
    _seed_conversation(SVC_CONV_EMPTY, documents=[SVC_DOC_EMPTY])
    yield
    with _admin() as conn:
        with conn.cursor() as cur:
            # Scope cleanup to the fixture's user only (FKs cascade chunks,
            # conversations, messages) — never wipe shared dev data.
            cur.execute("delete from documents where user_id = %s", (SVC_USER,))
            cur.execute("delete from conversations where user_id = %s", (SVC_USER,))
            cur.execute("delete from profiles where id = %s", (SVC_USER,))
        conn.commit()


async def _collect(prepared, *, in_flight: InFlightRegistry) -> list:
    events = []
    async for event in stream_chat_events(
        _SessionFactory,
        AI,
        prepared=prepared,
        settings=_SETTINGS,
        in_flight=in_flight,
    ):
        events.append(event)
    return events


def _accumulated(events) -> str:
    return "".join(event.data["text"] for event in events if event.event == "delta")


def _message_count(user_message_id: uuid.UUID) -> int:
    with _admin() as conn:
        row = conn.execute(
            "select count(*) from messages where id = %s", (user_message_id,)
        ).fetchone()
        return int(row[0])


# ---------------------------------------------------------------------------
# Context construction (T016, docs/rag.md §4)
# ---------------------------------------------------------------------------


def test_build_prompt_numbers_excerpts_with_locations():
    hits = [
        RetrievalHit(
            document_id=uuid.uuid4(),
            filename="refund-policy.pdf",
            page_number=4,
            chunk_index=2,
            similarity=0.9,
            content="The refund period is thirty days.",
        ),
        RetrievalHit(
            document_id=uuid.uuid4(),
            filename="terms.pdf",
            page_number=None,
            chunk_index=0,
            similarity=0.8,
            content="No refunds after thirty days.",
        ),
    ]
    messages = _build_prompt_messages("When does the refund expire?", hits)

    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[1]["content"] == "When does the refund expire?"

    system = messages[0]["content"]
    assert system.startswith("You answer questions exclusively")
    assert "Excerpts:" in system
    assert (
        "[1] refund-policy.pdf · page 4\n  The refund period is thirty days." in system
    )
    assert "[2] terms.pdf\n  No refunds after thirty days." in system


def test_build_prompt_without_hits_omits_excerpt_block():
    from app.services.chat import _SYSTEM_PROMPT

    messages = _build_prompt_messages("hello", [])
    assert "Excerpts:" not in messages[0]["content"]
    assert messages[0]["content"] == _SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Pipeline: pre-stream commit + protocol order (T016, contracts/chat.md §3)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_prepare_commits_user_message_before_stream():
    in_flight = InFlightRegistry()
    prepared = await prepare_chat(
        _SessionFactory,
        AI,
        _SETTINGS,
        identity=IDENTITY,
        conversation_id=SVC_CONV,
        question="What is the refund period?",
        idempotency_key=None,
        in_flight=in_flight,
    )
    assert prepared.idempotency_key is None

    with _admin() as conn:
        row = conn.execute(
            "select role, idempotency_key from messages where id = %s",
            (prepared.user_message_id,),
        ).fetchone()
    assert row is not None
    assert row[0] == "user"
    assert row[1] is None
    assert _message_count(prepared.user_message_id) == 1


@pytest.mark.anyio
async def test_stream_events_protocol_order_and_persistence():
    in_flight = InFlightRegistry()
    prepared = await prepare_chat(
        _SessionFactory,
        AI,
        _SETTINGS,
        identity=IDENTITY,
        conversation_id=SVC_CONV,
        question="What is the refund period?",
        idempotency_key=None,
        in_flight=in_flight,
    )
    events = await _collect(prepared, in_flight=in_flight)

    assert [event.event for event in events][0] == "meta"
    assert events[0].data == {"message_id": str(prepared.user_message_id)}
    assert events[-1].event == "done"
    assert all(event.event in {"delta", "meta", "done"} for event in events)

    deltas = [event for event in events if event.event == "delta"]
    assert len(deltas) > 1  # word-level deltas, not one blob

    expected = 'Answer for "What is the refund period?": '
    suffix = (
        "Based on your documents, the answer is clear and can be cited from the "
        "retrieved excerpts."
    )
    # Phase 8 flag: chat.py appends a [1] citation marker delta when sources
    # exist so dev/CI chat exercises the citation UI (quickstart S3).
    citation = "\n\n[1]"
    assert _accumulated(events) == expected + suffix + citation

    done = events[-1].data
    assert uuid.UUID(done["id"])
    assert done["llm_ms"] >= 0
    assert len(done["sources"]) == 1
    source = done["sources"][0]
    assert source["document_id"] == str(SVC_DOC_CHUNKED)
    assert source["filename"] == "refund-policy.pdf"
    assert source["page_number"] == 4
    assert source["chunk_index"] == 0
    assert isinstance(source["similarity"], float)

    with _admin() as conn:
        row = conn.execute(
            "select role, status, content from messages where id = %s",
            (done["id"],),
        ).fetchone()
    assert row[0] == "assistant"
    assert row[1] == "done"
    assert row[2] == expected + suffix + citation


@pytest.mark.anyio
async def test_non_streaming_provider_yields_single_delta():
    class NonStreamingProvider(FakeProvider):
        supports_streaming = False

    provider = NonStreamingProvider(embedding_dims=1024)
    in_flight = InFlightRegistry()
    prepared = await prepare_chat(
        _SessionFactory,
        provider,
        _SETTINGS,
        identity=IDENTITY,
        conversation_id=SVC_CONV,
        question="Non-streaming question",
        idempotency_key=None,
        in_flight=in_flight,
    )
    events = []
    async for event in stream_chat_events(
        _SessionFactory,
        provider,
        prepared=prepared,
        settings=_SETTINGS,
        in_flight=in_flight,
    ):
        events.append(event)

    deltas = [event for event in events if event.event == "delta"]
    assert len(deltas) == 1
    assert deltas[0].data["text"].startswith('Answer for "Non-streaming question":')
    assert events[-1].event == "done"


# ---------------------------------------------------------------------------
# Idempotency (T016, contracts/chat.md §3)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_duplicate_key_replays_completed_answer_with_stored_sources():
    in_flight = InFlightRegistry()
    key = "svc-replay-key"
    prepared = await prepare_chat(
        _SessionFactory,
        AI,
        _SETTINGS,
        identity=IDENTITY,
        conversation_id=SVC_CONV,
        question="Replay question",
        idempotency_key=key,
        in_flight=in_flight,
    )
    assert prepared.replay is None
    first_events = await _collect(prepared, in_flight=in_flight)
    first_done = first_events[-1].data
    expected_content = _accumulated(first_events)

    replayed = await prepare_chat(
        _SessionFactory,
        AI,
        _SETTINGS,
        identity=IDENTITY,
        conversation_id=SVC_CONV,
        question="Replay question",
        idempotency_key=key,
        in_flight=in_flight,
    )
    assert replayed.replay is not None
    replay_id, replay_content, replay_sources = replayed.replay
    assert replay_id == uuid.UUID(first_done["id"])
    assert replay_content == expected_content
    assert replay_sources == first_done["sources"]

    second_events = await _collect(replayed, in_flight=in_flight)
    assert [event.event for event in second_events] == ["meta", "delta", "done"]
    assert second_events[1].data == {"text": expected_content}
    assert second_events[2].data["id"] == first_done["id"]
    assert second_events[2].data["sources"] == first_done["sources"]
    assert second_events[2].data["llm_ms"] == 0

    with _admin() as conn:
        count = conn.execute(
            "select count(*) from messages where role = 'assistant' and id = %s",
            (first_done["id"],),
        ).fetchone()
    assert int(count[0]) == 1  # replay must not insert a second assistant row


@pytest.mark.anyio
async def test_duplicate_key_still_in_flight_raises_409_error():
    in_flight = InFlightRegistry()
    key = "svc-inflight-key"
    prepared = await prepare_chat(
        _SessionFactory,
        AI,
        _SETTINGS,
        identity=IDENTITY,
        conversation_id=SVC_CONV,
        question="In-flight question",
        idempotency_key=key,
        in_flight=in_flight,
    )
    assert prepared.replay is None

    in_flight.mark(str(SVC_CONV), key)
    with pytest.raises(IdempotencyInFlightError):
        await prepare_chat(
            _SessionFactory,
            AI,
            _SETTINGS,
            identity=IDENTITY,
            conversation_id=SVC_CONV,
            question="In-flight question",
            idempotency_key=key,
            in_flight=in_flight,
        )


# ---------------------------------------------------------------------------
# No qualifying chunks → canned answer, no LLM call (docs/rag.md §7)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_no_qualifying_chunks_skips_llm_and_answers_canned():
    class ExplodingProvider(FakeProvider):
        async def generate(self, messages, *, stream=False):
            raise AIProviderError("should never be called", provider="test")

    provider = ExplodingProvider(embedding_dims=1024)
    in_flight = InFlightRegistry()
    prepared = await prepare_chat(
        _SessionFactory,
        provider,
        _SETTINGS,
        identity=IDENTITY,
        conversation_id=SVC_CONV_EMPTY,
        question="Anything at all",
        idempotency_key=None,
        in_flight=in_flight,
    )
    assert prepared.hits == []

    events = []
    async for event in stream_chat_events(
        _SessionFactory,
        provider,
        prepared=prepared,
        settings=_SETTINGS,
        in_flight=in_flight,
    ):
        events.append(event)

    assert [event.event for event in events] == ["meta", "delta", "done"]
    assert events[1].data == {"text": _NO_RELEVANT_ANSWER}
    assert events[2].data["sources"] == []
