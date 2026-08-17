"""DB-gated schema shape tests (quickstart VS-2; contracts/database.md §1-3).

Requires the Phase 1 migration to be applied (make migrate) and a reachable
DATABASE_URL; skipped otherwise (same pattern as test_health.py).
"""

import asyncio
import os
import uuid

import psycopg
import pytest
from sqlalchemy import text

from app.db.engine import engine
from app.db.session import get_db
from app.schemas.conversation import ConversationIn, MAX_DOCUMENT_IDS, MAX_TITLE_CHARS
from app.schemas.message import MessageSendIn, MAX_CONTENT_CHARS

EXPECTED_TABLES = {
    "profiles",
    "documents",
    "document_chunks",
    "conversations",
    "conversation_documents",
    "messages",
}

EXPECTED_INDEXES = {
    "documents_user_idx",
    "documents_user_status_idx",
    "chunks_embedding_hnsw",
    "chunks_document_idx",
    "conversations_user_updated_idx",
    "conversations_user_pinned_updated_idx",
    "conversation_documents_document_idx",
    "messages_conversation_created_idx",
}


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


@pytest.fixture(scope="module")
def conn() -> psycopg.Connection:
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        yield connection


def _fetch(
    conn: psycopg.Connection, query: str, params: tuple | list | None = None
) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def test_all_application_tables_exist(conn: psycopg.Connection) -> None:
    rows = _fetch(
        conn,
        "select tablename from pg_tables where schemaname = 'public'",
    )
    names = {row[0] for row in rows}
    assert EXPECTED_TABLES <= names


def test_document_chunks_embedding_is_vector_1024(conn: psycopg.Connection) -> None:
    rows = _fetch(
        conn,
        """
        select format_type(a.atttypid, a.atttypmod)
        from pg_attribute a
        join pg_class c on c.oid = a.attrelid
        where c.relname = 'document_chunks' and a.attname = 'embedding'
        """,
    )
    assert rows == [("vector(1024)",)]


def test_document_status_enum_labels(conn: psycopg.Connection) -> None:
    rows = _fetch(
        conn,
        """
        select e.enumlabel
        from pg_enum e
        join pg_type t on t.oid = e.enumtypid
        where t.typname = 'document_status'
        """,
    )
    assert {row[0] for row in rows} == {
        "uploaded",
        "processing",
        "ready",
        "failed",
        "deleted",
        "superseded",
        "cancelled",
    }


def test_messages_role_check_constraint(conn: psycopg.Connection) -> None:
    rows = _fetch(
        conn,
        """
        select pg_get_constraintdef(oid)
        from pg_constraint
        where conrelid = 'messages'::regclass and contype = 'c'
        """,
    )
    definitions = [row[0] for row in rows]
    assert any("'user'::text" in d and "'assistant'::text" in d for d in definitions)


def test_document_chunks_unique_chunk_index(conn: psycopg.Connection) -> None:
    rows = _fetch(
        conn,
        """
        select pg_get_constraintdef(oid)
        from pg_constraint
        where conrelid = 'document_chunks'::regclass and contype = 'u'
        """,
    )
    assert any(
        "document_id" in d and "chunk_index" in d for d in [row[0] for row in rows]
    )


def test_all_indexes_present(conn: psycopg.Connection) -> None:
    rows = _fetch(
        conn,
        "select indexname from pg_indexes where schemaname = 'public'",
    )
    names = {row[0] for row in rows}
    assert EXPECTED_INDEXES <= names


def test_hnsw_index_definition(conn: psycopg.Connection) -> None:
    rows = _fetch(
        conn,
        "select indexdef from pg_indexes where indexname = 'chunks_embedding_hnsw'",
    )
    assert len(rows) == 1
    definition = rows[0][0].lower()
    assert "using hnsw" in definition
    assert "vector_l2_ops" in definition


def test_rls_enabled_and_forced_on_tenant_tables(conn: psycopg.Connection) -> None:
    rows = _fetch(
        conn,
        """
        select c.relname, c.relforcerowsecurity
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public'
          and c.relkind = 'r'
          and c.relname = any(%s)
          and c.relrowsecurity
        """,
        [list(EXPECTED_TABLES)],
    )
    assert {row[0] for row in rows} == EXPECTED_TABLES
    assert all(row[1] for row in rows)


def test_runtime_role_without_rls_bypass(conn: psycopg.Connection) -> None:
    rows = _fetch(
        conn,
        """
        select rolcanlogin, rolsuper, rolbypassrls
        from pg_roles
        where rolname = 'contextly_app'
        """,
    )
    assert rows == [(True, False, False)]


def test_runtime_role_has_table_privileges(conn: psycopg.Connection) -> None:
    for table in EXPECTED_TABLES:
        with conn.cursor() as cur:
            cur.execute(
                "select has_table_privilege('contextly_app', %s, 'SELECT'), "
                "       has_table_privilege('contextly_app', %s, 'INSERT'), "
                "       has_table_privilege('contextly_app', %s, 'UPDATE'), "
                "       has_table_privilege('contextly_app', %s, 'DELETE')",
                (table, table, table, table),
            )
            assert cur.fetchone() == (True, True, True, True), table


def test_engine_dialect_derived_from_database_url() -> None:
    assert engine.url.drivername == "postgresql+asyncpg"
    assert engine.url.get_backend_name() == "postgresql"


def test_engine_round_trip_select_1() -> None:
    async def _run() -> int:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            return result.scalar_one()

    assert asyncio.run(_run()) == 1


def test_get_db_session_round_trip() -> None:
    async def _run() -> int:
        async for session in get_db():
            result = await session.execute(text("SELECT 1"))
            return result.scalar_one()

    assert asyncio.run(_run()) == 1


@pytest.fixture(autouse=True)
def _dispose_engine_after_test() -> None:
    """Drop pooled connections so no connection is reused across event loops
    (each asyncio.run() above closes its loop)."""
    yield
    asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# Request schema validation (T025, contracts/chat.md §5)
# ---------------------------------------------------------------------------


def test_message_send_in_trims_whitespace() -> None:
    assert MessageSendIn(content="   what is the refund period?  ").content == (
        "what is the refund period?"
    )


def test_message_send_in_rejects_blank_or_missing_content() -> None:
    for bad in ("", "   ", "\t\n"):
        with pytest.raises(ValueError):
            MessageSendIn(content=bad)


def test_message_send_in_structural_bound() -> None:
    assert len(MessageSendIn(content="x" * MAX_CONTENT_CHARS).content) == (
        MAX_CONTENT_CHARS
    )
    with pytest.raises(ValueError):
        MessageSendIn(content="x" * (MAX_CONTENT_CHARS + 1))


def test_conversation_in_title_rules() -> None:
    assert ConversationIn(title="  Job applications  ").title == "Job applications"
    assert ConversationIn().title is None
    for bad in ("", "   ", "x" * (MAX_TITLE_CHARS + 1)):
        with pytest.raises(ValueError):
            ConversationIn(title=bad)


def test_conversation_in_document_ids_rules() -> None:
    ids = [str(uuid.uuid4()) for _ in range(MAX_DOCUMENT_IDS)]
    assert len(ConversationIn(document_ids=ids).document_ids or []) == MAX_DOCUMENT_IDS
    assert ConversationIn(document_ids=[]).document_ids == []
    with pytest.raises(ValueError):
        ConversationIn(document_ids=ids + [str(uuid.uuid4())])
    with pytest.raises(ValueError):
        ConversationIn(document_ids=["not-a-uuid"])
