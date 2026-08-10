"""Retrieval service test matrix (quickstart VS-1..VS-4; spec SC-002).

DB-gated: skipped when DATABASE_URL is unreachable (same pattern as
test_worker_integration.py). Seeds users/documents/conversations/chunks with
hand-written 1024-dim vectors via an admin psycopg connection, then drives
`search_ready_documents` on a session switched to the contextly_app runtime
role with the caller's claim — the exact session setup `get_current_user`
performs (deps.py), so RLS is active in every test. Async helpers run under
`asyncio.run` (repo pattern — no pytest-asyncio).

Ranking control: the injected `_FixedVectorProvider` returns a hand-chosen
query vector, so L2 distances and `1 - distance` similarities are exact and
assertable. The fake provider's determinism is irrelevant here because we
control both sides of the distance.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.security.identity import Identity
from app.services.retrieval import (
    ConversationNotFoundError,
    RetrievalHit,
    search_ready_documents,
)

DIMS = 1024
RUNTIME_ROLE = "contextly_app"

USER_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_B = uuid.UUID("22222222-2222-2222-2222-222222222222")

_SETTINGS = Settings(
    database_url=os.getenv("DATABASE_URL", "postgresql://localhost/contextly"),
    auth_mode="dev",
    app_env="dev",
    retrieval_top_k=6,
    retrieval_ef_search=40,
)

_TEST_ENGINE = create_async_engine(
    _SETTINGS.database_url.replace("postgresql://", "postgresql+asyncpg://", 1),
    poolclass=NullPool,
)
_SessionFactory = async_sessionmaker(_TEST_ENGINE, expire_on_commit=False)


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


def _vec(*values: float) -> str:
    """A 1024-dim vector literal with the given leading dims and zeros elsewhere."""
    dims = [0.0] * DIMS
    for index, value in enumerate(values):
        dims[index] = float(value)
    return "[" + ",".join(repr(v) for v in dims) + "]"


def _seed_user(user_id: uuid.UUID) -> None:
    with _admin() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into auth.users (id) values (%s) "
                "on conflict (id) do nothing",
                (user_id,),
            )
            cur.execute(
                "insert into profiles (id, email) values (%s, %s) "
                "on conflict (id) do nothing",
                (user_id, f"{user_id}@example.com"),
            )
        conn.commit()


def _seed_document(
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    status: str = "ready",
    filename: str | None = None,
) -> None:
    with _admin() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into documents "
                "(id, user_id, filename, storage_path, file_size_bytes, status, total_chunks) "
                "values (%s, %s, %s, %s, 100, %s, 1)",
                (
                    document_id,
                    user_id,
                    filename or f"{document_id}.pdf",
                    f"{user_id}/docs/{document_id}.pdf",
                    status,
                ),
            )
        conn.commit()


def _seed_chunk(
    chunk_id: uuid.UUID,
    document_id: uuid.UUID,
    *,
    index: int,
    content: str,
    vector: str,
    page_number: int = 1,
) -> None:
    with _admin() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into document_chunks "
                "(id, document_id, chunk_index, content, page_number, token_count, metadata, embedding) "
                "values (%s, %s, %s, %s, %s, 10, '{}'::jsonb, %s::vector)",
                (chunk_id, document_id, index, content, page_number, vector),
            )
        conn.commit()


def _seed_conversation(
    conversation_id: uuid.UUID, user_id: uuid.UUID, *, deleted: bool = False
) -> None:
    with _admin() as conn:
        with conn.cursor() as cur:
            if deleted:
                cur.execute(
                    "insert into conversations (id, user_id, title, deleted_at) "
                    "values (%s, %s, %s, now())",
                    (conversation_id, user_id, "deleted"),
                )
            else:
                cur.execute(
                    "insert into conversations (id, user_id, title) "
                    "values (%s, %s, %s)",
                    (conversation_id, user_id, "test"),
                )
        conn.commit()


def _link(conversation_id: uuid.UUID, document_id: uuid.UUID) -> None:
    with _admin() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into conversation_documents (conversation_id, document_id) "
                "values (%s, %s)",
                (conversation_id, document_id),
            )
        conn.commit()


def _cleanup(*user_ids: uuid.UUID) -> None:
    with _admin() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from profiles where id = any(%s)", (list(user_ids),))
        conn.commit()


class _FixedVectorProvider:
    """Test double: embed returns exactly the query vector we design."""

    embedding_dims = DIMS
    embedding_model = "test-fixed"

    def __init__(self, vector: list[float]):
        self.vector = vector

    async def embed(
        self, texts: list[str], *, batch_size: int = 32
    ) -> list[list[float]]:
        return [list(self.vector) for _ in texts]


def _query_vector(*values: float) -> _FixedVectorProvider:
    dims = [0.0] * DIMS
    for index, value in enumerate(values):
        dims[index] = float(value)
    return _FixedVectorProvider(dims)


@asynccontextmanager
async def _session_as(user_id: uuid.UUID) -> AsyncIterator:
    """A session under the runtime role + the caller's RLS claim (deps.py parity)."""
    async with _SessionFactory() as db:
        await db.execute(text(f"SET LOCAL ROLE {RUNTIME_ROLE}"))
        await db.execute(
            text("SELECT set_config('request.jwt.claim.sub', :sub, true)"),
            {"sub": str(user_id)},
        )
        try:
            yield db
        finally:
            await db.rollback()


async def _search(
    *,
    user: uuid.UUID,
    conversation_id: uuid.UUID,
    question: str,
    provider: _FixedVectorProvider,
    top_k: int | None = None,
) -> list[RetrievalHit]:
    identity = Identity(user_id=user)
    async with _session_as(user) as db:
        return await search_ready_documents(
            db,
            provider,
            _SETTINGS,
            identity=identity,
            conversation_id=conversation_id,
            question=question,
            top_k=top_k,
        )


# ---------------------------------------------------------------------------
# US1: ranked hits with full source metadata (quickstart VS-1)
# ---------------------------------------------------------------------------


def test_ranks_hits_by_similarity_with_full_metadata() -> None:
    _seed_user(USER_A)
    doc_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    try:
        _seed_document(doc_id, USER_A, filename="refund-policy.pdf")
        _seed_conversation(conversation_id, USER_A)
        _link(conversation_id, doc_id)
        # Query q = [1,0,0,...]: L2 distances → similarities 1 - d.
        _seed_chunk(uuid.uuid4(), doc_id, index=0, content="close", vector=_vec(0.8))
        _seed_chunk(uuid.uuid4(), doc_id, index=1, content="closest", vector=_vec(1.0))
        _seed_chunk(uuid.uuid4(), doc_id, index=2, content="far", vector=_vec(0.2))

        hits = asyncio.run(
            _search(
                user=USER_A,
                conversation_id=conversation_id,
                question="refund?",
                provider=_query_vector(1.0),
            )
        )

        assert [hit.content for hit in hits] == ["closest", "close", "far"]
        assert [round(hit.similarity, 4) for hit in hits] == [1.0, 0.8, 0.2]
        for hit in hits:
            assert hit.document_id == doc_id
            assert hit.filename == "refund-policy.pdf"
            assert hit.page_number == 1
            assert isinstance(hit.chunk_index, int)
            assert isinstance(hit.content, str)
    finally:
        _cleanup(USER_A)


def test_default_top_k_is_six_and_override_honored() -> None:
    _seed_user(USER_A)
    doc_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    try:
        _seed_document(doc_id, USER_A)
        _seed_conversation(conversation_id, USER_A)
        _link(conversation_id, doc_id)
        for index in range(8):
            _seed_chunk(
                uuid.uuid4(),
                doc_id,
                index=index,
                content=f"chunk {index}",
                vector=_vec(0.5 + index / 10.0),
            )

        default_hits = asyncio.run(
            _search(
                user=USER_A,
                conversation_id=conversation_id,
                question="everything?",
                provider=_query_vector(1.0),
            )
        )
        assert len(default_hits) == _SETTINGS.retrieval_top_k == 6

        short_hits = asyncio.run(
            _search(
                user=USER_A,
                conversation_id=conversation_id,
                question="everything?",
                provider=_query_vector(1.0),
                top_k=2,
            )
        )
        assert len(short_hits) == 2
    finally:
        _cleanup(USER_A)


# ---------------------------------------------------------------------------
# US2: scope matrix — tenant, conversation, readiness (quickstart VS-2)
# ---------------------------------------------------------------------------


def test_tenant_isolation_never_leaks_other_users_chunks() -> None:
    _seed_user(USER_A)
    _seed_user(USER_B)
    doc_a = uuid.uuid4()
    doc_b = uuid.uuid4()
    conversation_a = uuid.uuid4()
    try:
        _seed_document(doc_a, USER_A)
        _seed_document(doc_b, USER_B)
        _seed_conversation(conversation_a, USER_A)
        _link(conversation_a, doc_a)
        _seed_chunk(uuid.uuid4(), doc_a, index=0, content="mine", vector=_vec(0.1))
        # User B's chunk is an exact match for the query — the leak that must
        # never happen even when it would out-rank everything of user A's.
        _seed_chunk(uuid.uuid4(), doc_b, index=0, content="theirs", vector=_vec(1.0))

        hits = asyncio.run(
            _search(
                user=USER_A,
                conversation_id=conversation_a,
                question="anything?",
                provider=_query_vector(1.0),
                top_k=50,
            )
        )

        assert [hit.content for hit in hits] == ["mine"]
        assert all(hit.document_id == doc_a for hit in hits)
    finally:
        _cleanup(USER_A, USER_B)


def test_unselected_ready_documents_are_excluded() -> None:
    _seed_user(USER_A)
    selected = uuid.uuid4()
    unselected = uuid.uuid4()
    conversation_id = uuid.uuid4()
    try:
        _seed_document(selected, USER_A)
        _seed_document(unselected, USER_A)
        _seed_conversation(conversation_id, USER_A)
        _link(conversation_id, selected)
        _seed_chunk(uuid.uuid4(), selected, index=0, content="selected", vector=_vec(0.1))
        # An exact query match in a ready-but-unselected document must be invisible.
        _seed_chunk(uuid.uuid4(), unselected, index=0, content="unselected", vector=_vec(1.0))

        hits = asyncio.run(
            _search(
                user=USER_A,
                conversation_id=conversation_id,
                question="anything?",
                provider=_query_vector(1.0),
                top_k=50,
            )
        )

        assert [hit.content for hit in hits] == ["selected"]
        assert all(hit.document_id == selected for hit in hits)
    finally:
        _cleanup(USER_A)


def test_not_ready_documents_are_excluded() -> None:
    _seed_user(USER_A)
    ready = uuid.uuid4()
    conversation_id = uuid.uuid4()
    try:
        _seed_document(ready, USER_A)
        _seed_conversation(conversation_id, USER_A)
        _link(conversation_id, ready)
        _seed_chunk(uuid.uuid4(), ready, index=0, content="ready chunk", vector=_vec(0.1))
        for index, status in enumerate(("uploaded", "processing", "failed")):
            other = uuid.uuid4()
            _seed_document(other, USER_A, status=status)
            _link(conversation_id, other)
            _seed_chunk(uuid.uuid4(), other, index=0, content=status, vector=_vec(1.0))

        hits = asyncio.run(
            _search(
                user=USER_A,
                conversation_id=conversation_id,
                question="anything?",
                provider=_query_vector(1.0),
                top_k=50,
            )
        )

        assert [hit.content for hit in hits] == ["ready chunk"]
        assert all(hit.document_id == ready for hit in hits)
    finally:
        _cleanup(USER_A)


def test_missing_conversation_raises_not_found() -> None:
    _seed_user(USER_A)
    try:
        with pytest.raises(ConversationNotFoundError):
            asyncio.run(
                _search(
                    user=USER_A,
                    conversation_id=uuid.uuid4(),
                    question="anything?",
                    provider=_query_vector(1.0),
                )
            )
    finally:
        _cleanup(USER_A)


def test_foreign_conversation_raises_not_found() -> None:
    _seed_user(USER_A)
    _seed_user(USER_B)
    conversation_b = uuid.uuid4()
    try:
        _seed_conversation(conversation_b, USER_B)
        with pytest.raises(ConversationNotFoundError):
            asyncio.run(
                _search(
                    user=USER_A,
                    conversation_id=conversation_b,
                    question="anything?",
                    provider=_query_vector(1.0),
                )
            )
    finally:
        _cleanup(USER_A, USER_B)


def test_deleted_conversation_raises_not_found() -> None:
    _seed_user(USER_A)
    conversation_id = uuid.uuid4()
    try:
        _seed_conversation(conversation_id, USER_A, deleted=True)
        with pytest.raises(ConversationNotFoundError):
            asyncio.run(
                _search(
                    user=USER_A,
                    conversation_id=conversation_id,
                    question="anything?",
                    provider=_query_vector(1.0),
                )
            )
    finally:
        _cleanup(USER_A)


# ---------------------------------------------------------------------------
# US3: empty retrieval is graceful and logged (quickstart VS-3)
# ---------------------------------------------------------------------------


def test_empty_when_conversation_has_no_linked_documents() -> None:
    _seed_user(USER_A)
    conversation_id = uuid.uuid4()
    try:
        _seed_conversation(conversation_id, USER_A)
        hits = asyncio.run(
            _search(
                user=USER_A,
                conversation_id=conversation_id,
                question="anything?",
                provider=_query_vector(1.0),
            )
        )
        assert hits == []
    finally:
        _cleanup(USER_A)


def test_empty_when_linked_documents_are_not_ready() -> None:
    _seed_user(USER_A)
    doc_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    try:
        _seed_document(doc_id, USER_A, status="processing")
        _seed_conversation(conversation_id, USER_A)
        _link(conversation_id, doc_id)
        _seed_chunk(uuid.uuid4(), doc_id, index=0, content="not ready", vector=_vec(1.0))

        hits = asyncio.run(
            _search(
                user=USER_A,
                conversation_id=conversation_id,
                question="anything?",
                provider=_query_vector(1.0),
            )
        )
        assert hits == []
    finally:
        _cleanup(USER_A)


def test_empty_is_scope_driven_not_similarity_driven(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No hard threshold (docs/rag.md §2): any in-scope chunk is a candidate, so
    'empty' means an empty scope, not a low score. This guards the no-threshold
    default against regression (a future soft floor is a Phase 12 tuning decision)."""
    _seed_user(USER_A)
    doc_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    try:
        _seed_document(doc_id, USER_A)
        _seed_conversation(conversation_id, USER_A)
        _link(conversation_id, doc_id)
        _seed_chunk(uuid.uuid4(), doc_id, index=0, content="only chunk", vector=_vec(0.0))

        with caplog.at_level(logging.INFO, logger="app.services.retrieval"):
            hits = asyncio.run(
                _search(
                    user=USER_A,
                    conversation_id=conversation_id,
                    question="totally unrelated?",
                    provider=_query_vector(1.0),
                )
            )

        assert len(hits) == 1
        assert "class=hit" in caplog.text
        assert "class=empty" not in caplog.text
    finally:
        _cleanup(USER_A)


def test_empty_result_is_logged_with_class_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _seed_user(USER_A)
    conversation_id = uuid.uuid4()
    try:
        _seed_conversation(conversation_id, USER_A)
        with caplog.at_level(logging.INFO, logger="app.services.retrieval"):
            hits = asyncio.run(
                _search(
                    user=USER_A,
                    conversation_id=conversation_id,
                    question="anything?",
                    provider=_query_vector(1.0),
                )
            )
        assert hits == []
        assert "class=empty" in caplog.text
    finally:
        _cleanup(USER_A)
