"""DB-gated RLS tenant-isolation tests (quickstart VS-3; docs/testing.md matrix
items 7/10; contracts/database.md §2).

Two users A and B with dependent rows; a session switched to the contextly_app
runtime role with A's identity claim must see only A's rows everywhere, reject
cross-owner writes, and fail closed with no claim. Skipped when DATABASE_URL is
unreachable (same pattern as test_health.py).
"""
import os
import uuid

import psycopg
import pytest

TABLES = (
    "profiles",
    "documents",
    "document_chunks",
    "conversations",
    "conversation_documents",
    "messages",
)

RUNTIME_ROLE = "contextly_app"


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


class FixtureRows:
    def __init__(self) -> None:
        self.user_a = uuid.uuid4()
        self.user_b = uuid.uuid4()
        self.doc_a = uuid.uuid4()
        self.doc_b = uuid.uuid4()
        self.chunk_a = uuid.uuid4()
        self.chunk_b = uuid.uuid4()
        self.conv_a = uuid.uuid4()
        self.conv_b = uuid.uuid4()
        self.message_a = uuid.uuid4()
        self.message_b = uuid.uuid4()


@pytest.fixture(scope="module")
def rows() -> FixtureRows:
    data = FixtureRows()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        try:
            with conn.cursor() as cur:
                for user, email in (
                    (data.user_a, "a@example.com"),
                    (data.user_b, "b@example.com"),
                ):
                    cur.execute(
                        "insert into auth.users (id) values (%s)",
                        (user,),
                    )
                    cur.execute(
                        "insert into profiles (id, email) values (%s, %s)",
                        (user, email),
                    )
                for doc, user in ((data.doc_a, data.user_a), (data.doc_b, data.user_b)):
                    cur.execute(
                        "insert into documents (id, user_id, filename, storage_path, "
                        "file_size_bytes) values (%s, %s, %s, %s, 100)",
                        (doc, user, f"{doc}.pdf", f"{user}/docs/{doc}.pdf"),
                    )
                for chunk, doc in (
                    (data.chunk_a, data.doc_a),
                    (data.chunk_b, data.doc_b),
                ):
                    cur.execute(
                        "insert into document_chunks (id, document_id, chunk_index, "
                        "content) values (%s, %s, 0, %s)",
                        (chunk, doc, f"chunk for {doc}"),
                    )
                for conv, user in (
                    (data.conv_a, data.user_a),
                    (data.conv_b, data.user_b),
                ):
                    cur.execute(
                        "insert into conversations (id, user_id, title) "
                        "values (%s, %s, %s)",
                        (conv, user, f"conv {conv}"),
                    )
                cur.execute(
                    "insert into conversation_documents (conversation_id, document_id) "
                    "values (%s, %s), (%s, %s)",
                    (data.conv_a, data.doc_a, data.conv_b, data.doc_b),
                )
                for message, conv in (
                    (data.message_a, data.conv_a),
                    (data.message_b, data.conv_b),
                ):
                    cur.execute(
                        "insert into messages (id, conversation_id, role, content) "
                        "values (%s, %s, 'user', %s)",
                        (message, conv, f"message for {conv}"),
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    yield data
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from messages where id = any(%s)",
                ([data.message_a, data.message_b],),
            )
            cur.execute(
                "delete from conversation_documents where conversation_id = any(%s)",
                ([data.conv_a, data.conv_b],),
            )
            cur.execute(
                "delete from conversations where id = any(%s)",
                ([data.conv_a, data.conv_b],),
            )
            cur.execute(
                "delete from document_chunks where id = any(%s)",
                ([data.chunk_a, data.chunk_b],),
            )
            cur.execute(
                "delete from documents where id = any(%s)",
                ([data.doc_a, data.doc_b],),
            )
            cur.execute(
                "delete from profiles where id = any(%s)",
                ([data.user_a, data.user_b],),
            )
        conn.commit()


def _as_role(rows: FixtureRows, claim: str | None) -> psycopg.Connection:
    """Connection switched to the runtime role, optionally with A's claim."""
    conn = psycopg.connect(os.environ["DATABASE_URL"])
    with conn.cursor() as cur:
        cur.execute(f"set role {RUNTIME_ROLE}")
        if claim is not None:
            cur.execute(
                "select set_config('request.jwt.claim.sub', %s, false)",
                (claim,),
            )
    return conn


def test_rls_isolation_as_user_a(rows: FixtureRows) -> None:
    conn = _as_role(rows, str(rows.user_a))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select count(*) from documents where user_id = %s",
                (rows.user_a,),
            )
            assert cur.fetchone()[0] == 1
            cur.execute(
                "select count(*) from documents where user_id = %s",
                (rows.user_b,),
            )
            assert cur.fetchone()[0] == 0
            cur.execute(
                "select count(*) from profiles where id = %s",
                (rows.user_b,),
            )
            assert cur.fetchone()[0] == 0
            cur.execute(
                "select count(*) from conversations where user_id = %s",
                (rows.user_b,),
            )
            assert cur.fetchone()[0] == 0
            cur.execute(
                "select count(*) from conversation_documents where conversation_id = %s",
                (rows.conv_b,),
            )
            assert cur.fetchone()[0] == 0
            cur.execute(
                "select count(*) from messages where conversation_id = %s",
                (rows.conv_b,),
            )
            assert cur.fetchone()[0] == 0
            cur.execute(
                "select count(*) from document_chunks where document_id = %s",
                (rows.doc_b,),
            )
            assert cur.fetchone()[0] == 0
            cur.execute(
                "select count(*) from document_chunks where document_id = %s",
                (rows.doc_a,),
            )
            assert cur.fetchone()[0] == 1
    finally:
        conn.close()


def test_rls_blocks_cross_owner_writes(rows: FixtureRows) -> None:
    conn = _as_role(rows, str(rows.user_a))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "update documents set filename = 'x' where id = %s",
                (rows.doc_b,),
            )
            assert cur.rowcount == 0
            cur.execute(
                "delete from documents where id = %s",
                (rows.doc_b,),
            )
            assert cur.rowcount == 0
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(
                    "insert into documents (user_id, filename, storage_path, "
                    "file_size_bytes) values (%s, %s, %s, 100)",
                    (rows.user_b, "sneaky.pdf", f"{rows.user_b}/docs/sneaky.pdf"),
                )
            conn.rollback()
    finally:
        conn.close()


def test_rls_fails_closed_without_claim(rows: FixtureRows) -> None:
    conn = _as_role(rows, None)
    try:
        with conn.cursor() as cur:
            for table in TABLES:
                cur.execute(f"select count(*) from {table}")
                assert cur.fetchone()[0] == 0, table
    finally:
        conn.close()
