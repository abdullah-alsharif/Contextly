"""The 10-test multi-tenancy isolation matrix (spec FR-001; docs/testing.md §3).

Two real users A and B with independent documents, conversations, selections,
messages, and chunked documents. Every cross-tenant attempt must resolve to 404
— never 403 (docs/security.md §2 anti-enumeration; docs/api.md §6) — and leave
the owner's data untouched. This module contains EXACTLY 10 test functions; CI
gates the count (spec FR-007). Row 10 also proves the owner download-url path
issues a short-lived signed URL (~5 min, docs/api.md §5).

DB-gated like test_documents_api.py (skipped when DATABASE_URL is unreachable).
Storage is the local provider rooted in a tmp dir; the AI provider is the fake
(deterministic embeddings), so retrieval assertions are exact.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.services import pipeline
from tests.pdf_fixtures import make_pdf
from tests.security import _harness

pytestmark = _harness.DB_GATE

USER_A = _harness.USER_A
USER_B = _harness.USER_B

B_MARKER = "B-SECRET-REFUND-WINDOW-31-DAYS"


def _token(user: uuid.UUID) -> str:
    return _harness.token(user)


class Seeded:
    """Rows the matrix needs: two independent tenants, fully processed."""

    def __init__(self, doc_a: uuid.UUID, doc_b: uuid.UUID, conv_a: uuid.UUID,
                 conv_b: uuid.UUID, message_b: uuid.UUID) -> None:
        self.doc_a = doc_a
        self.doc_b = doc_b
        self.conv_a = conv_a
        self.conv_b = conv_b
        self.message_b = message_b


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    storage_dir = tmp_path_factory.mktemp("storage")
    # High budgets: the matrix exercises isolation, not throttling. The
    # app.state.ai_provider/session_factory are the harness instances.
    with _harness.make_client(str(storage_dir)) as test_client:
        yield test_client


def _process_to_ready(client: TestClient, document_id: uuid.UUID) -> None:
    """Drive the Phase-4 pipeline for OUR document into 'ready' (chunks).

    Deterministic on a shared dev DB: claim OUR row (mirroring worker_claim_next's
    transition, but pinned by id) instead of claim_next — which takes ANY
    eligible 'uploaded' row, so a stray leftover from other dev usage would be
    claimed instead and fail the whole fixture (observed as 10 errors). The
    lease we set makes the live worker unable to steal the row afterward.
    """

    async def process() -> None:
        storage = client.app.state.storage_provider
        ai = client.app.state.ai_provider
        session_factory = client.app.state.session_factory
        settings = Settings(auth_mode="dev", app_env="dev")
        async with session_factory() as db:
            claimed = await _claim_owned(db, document_id)
            await db.commit()
            if claimed is None:
                return  # already ready/failed (redo, or a race the worker won)
        async with session_factory() as db:
            outcome = await pipeline.process_claimed_document(
                db, storage, settings, claimed, ai
            )
            assert outcome == "ready"
            await db.commit()

    asyncio.run(process())


async def _claim_owned(
    db: AsyncSession, document_id: uuid.UUID
) -> pipeline.ClaimedDocument | None:
    """Mirror worker_claim_next's transition (status → 'processing', lease set),
    but pinned to OUR id. Returns None when the row is no longer claimable.
    """
    row = (
        await db.execute(
            text("select status from documents where id = :id"),
            {"id": str(document_id)},
        )
    ).one_or_none()
    if row is None or row.status != "uploaded":
        return None
    result = await db.execute(
        text(
            """
            update documents
            set status = 'processing',
                lease_until = now() + make_interval(secs => :lease_seconds),
                updated_at = now()
            where id = :document_id and status = 'uploaded' and deleted_at is null
            returning id, user_id, storage_path, filename, retry_count
            """
        ),
        {"document_id": str(document_id), "lease_seconds": 300},
    )
    r = result.one_or_none()
    if r is None:
        return None  # claimed concurrently; nothing to do here
    return pipeline.ClaimedDocument(
        id=r.id,
        user_id=r.user_id,
        storage_path=r.storage_path,
        filename=r.filename,
        retry_count=r.retry_count,
    )


@pytest.fixture(scope="module")
def seeded(client: TestClient) -> Seeded:
    """Two fully-processed tenants (uploads, ready docs, convs, a B message)."""
    with psycopg.connect(_harness.database_url()) as conn:
        with conn.cursor() as cur:
            # Idempotent re-seed (reruns on dirty dev DBs).
            cur.execute(
                "delete from document_chunks where document_id in "
                "(select id from documents where user_id = any(%s))",
                ([str(USER_A), str(USER_B)],),
            )
            cur.execute(
                "delete from messages where conversation_id in "
                "(select id from conversations where user_id = any(%s))",
                ([str(USER_A), str(USER_B)],),
            )
            cur.execute(
                "delete from conversation_documents where conversation_id in "
                "(select id from conversations where user_id = any(%s))",
                ([str(USER_A), str(USER_B)],),
            )
            cur.execute(
                "delete from conversations where user_id = any(%s)",
                ([str(USER_A), str(USER_B)],),
            )
            cur.execute(
                "delete from documents where user_id = any(%s)",
                ([str(USER_A), str(USER_B)],),
            )
            cur.execute(
                "delete from profiles where id = any(%s)",
                ([str(USER_A), str(USER_B)],),
            )
        conn.commit()

    def upload(user: uuid.UUID, *, pages: list[str], filename: str) -> uuid.UUID:
        response = client.post(
            "/api/v1/documents",
            headers={"Authorization": f"Bearer {_token(user)}"},
            files={"file": (filename, make_pdf(pages), "application/pdf")},
        )
        assert response.status_code == 201, response.text
        return uuid.UUID(response.json()["id"])

    doc_a = upload(USER_A, pages=["A refunds are 15 days."], filename="a.pdf")
    doc_b = upload(
        USER_B,
        pages=[f"Confidential: the refund window is {B_MARKER}."],
        filename="b.pdf",
    )
    _process_to_ready(client, doc_a)
    _process_to_ready(client, doc_b)

    def conversation(user: uuid.UUID, document_id: uuid.UUID) -> uuid.UUID:
        response = client.post(
            "/api/v1/conversations",
            headers={"Authorization": f"Bearer {_token(user)}"},
            json={"title": "seed", "document_ids": [str(document_id)]},
        )
        assert response.status_code == 201, response.text
        return uuid.UUID(response.json()["id"])

    conv_a = conversation(USER_A, doc_a)
    conv_b = conversation(USER_B, doc_b)

    # B's private message (seeded directly; the messages API is covered by
    # Phase 7 chat tests). Proves A can never observe or mutate it.
    message_b = uuid.uuid4()
    with psycopg.connect(_harness.database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into messages (id, conversation_id, role, content) "
                "values (%s, %s, 'user', %s)",
                (message_b, conv_b, f"where is {B_MARKER}?"),
            )
        conn.commit()

    yield Seeded(doc_a, doc_b, conv_a, conv_b, message_b)

    with psycopg.connect(_harness.database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from document_chunks where document_id = any(%s)",
                ([str(doc_a), str(doc_b)],),
            )
            cur.execute(
                "delete from messages where conversation_id = any(%s)",
                ([str(conv_a), str(conv_b)],),
            )
            cur.execute(
                "delete from conversation_documents where conversation_id = any(%s)",
                ([str(conv_a), str(conv_b)],),
            )
            cur.execute(
                "delete from conversations where id = any(%s)",
                ([str(conv_a), str(conv_b)],),
            )
            cur.execute(
                "delete from documents where id = any(%s)",
                ([str(doc_a), str(doc_b)],),
            )
            cur.execute(
                "delete from profiles where id = any(%s)",
                ([str(USER_A), str(USER_B)],),
            )
        conn.commit()


def _admin_sql(query: str, params: tuple) -> list[tuple]:
    """Superuser query (bypasses RLS) for owner-data-intact assertions."""
    with psycopg.connect(_harness.database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return list(cur.fetchall())


def _as_role(claim: uuid.UUID | None, query: str, params: tuple) -> list[tuple]:
    """Query as the runtime RLS role under the given user's claim (multi-tenancy.md §2).

    A `None` claim means no identity: RLS fails closed (0 rows everywhere).
    """
    with psycopg.connect(_harness.database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("set role contextly_app")
            if claim is not None:
                cur.execute(
                    "select set_config('request.jwt.claim.sub', %s, false)",
                    (str(claim),),
                )
            cur.execute(query, params)
            return list(cur.fetchall())


# ---------------------------------------------------------------------------
# Matrix rows (docs/testing.md §3). Each asserts 404 and never 403.
# ---------------------------------------------------------------------------


def test_matrix_1_document_read_cross_tenant_404_not_403(
    client: TestClient, seeded: Seeded
) -> None:
    response = client.get(
        f"/api/v1/documents/{seeded.doc_b}",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
    )
    assert response.status_code == 404, response.text


def test_matrix_2_document_delete_cross_tenant_404_owner_intact(
    client: TestClient, seeded: Seeded
) -> None:
    response = client.delete(
        f"/api/v1/documents/{seeded.doc_b}",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
    )
    assert response.status_code == 404, response.text
    rows = _admin_sql(
        "select deleted_at from documents where id = %s and user_id = %s",
        (seeded.doc_b, USER_B),
    )
    assert rows and rows[0][0] is None


def test_matrix_3_conversation_read_cross_tenant_404_not_403(
    client: TestClient, seeded: Seeded
) -> None:
    response = client.get(
        f"/api/v1/conversations/{seeded.conv_b}",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
    )
    assert response.status_code == 404, response.text


def test_matrix_4_selection_of_foreign_document_404_unchanged(
    client: TestClient, seeded: Seeded
) -> None:
    # Update path: A tries to attach B's document to A's conversation.
    response = client.patch(
        f"/api/v1/conversations/{seeded.conv_a}",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
        json={"document_ids": [str(seeded.doc_b)]},
    )
    assert response.status_code == 404, response.text
    rows = _admin_sql(
        "select document_id from conversation_documents where conversation_id = %s",
        (seeded.conv_a,),
    )
    assert [r[0] for r in rows] == [seeded.doc_a]  # selection unchanged

    # Create path: A cannot even create a conversation selecting B's document.
    response = client.post(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
        json={"document_ids": [str(seeded.doc_b)]},
    )
    assert response.status_code == 404, response.text


def test_matrix_5_conversation_delete_cross_tenant_404_owner_intact(
    client: TestClient, seeded: Seeded
) -> None:
    response = client.delete(
        f"/api/v1/conversations/{seeded.conv_b}",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
    )
    assert response.status_code == 404, response.text
    rows = _admin_sql(
        "select deleted_at from conversations where id = %s and user_id = %s",
        (seeded.conv_b, USER_B),
    )
    assert rows and rows[0][0] is None


def test_matrix_6_message_history_cross_tenant_404_not_403(
    client: TestClient, seeded: Seeded
) -> None:
    response = client.get(
        f"/api/v1/conversations/{seeded.conv_b}/messages",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
    )
    assert response.status_code == 404, response.text


def test_matrix_7_message_send_cross_tenant_404_no_footprint(
    client: TestClient, seeded: Seeded
) -> None:
    before = _admin_sql(
        "select count(*) from messages where conversation_id = %s",
        (seeded.conv_b,),
    )[0][0]
    response = client.post(
        f"/api/v1/conversations/{seeded.conv_b}/messages",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
        json={"content": "how much is the refund?"},
    )
    assert response.status_code == 404, response.text
    after = _admin_sql(
        "select count(*) from messages where conversation_id = %s", (seeded.conv_b,)
    )[0][0]
    assert after == before


def test_matrix_8_chunks_and_messages_invisible_under_rls(
    client: TestClient, seeded: Seeded
) -> None:
    # Positive control: B sees B's own row graph under the runtime role + claim.
    for query, param in (
        ("select count(*) from document_chunks where document_id = %s", seeded.doc_b),
        (
            "select count(*) from conversation_documents where conversation_id = %s",
            seeded.conv_b,
        ),
        ("select count(*) from messages where conversation_id = %s", seeded.conv_b),
    ):
        assert _as_role(USER_B, query, (param,))[0][0] == 1
    # Negative: A sees none of B's chunks, selection, or messages (RLS).
    for query, param in (
        ("select count(*) from document_chunks where document_id = %s", seeded.doc_b),
        (
            "select count(*) from conversation_documents where conversation_id = %s",
            seeded.conv_b,
        ),
        ("select count(*) from messages where conversation_id = %s", seeded.conv_b),
    ):
        assert _as_role(USER_A, query, (param,))[0][0] == 0
    # Negative, no claim at all: RLS fails closed everywhere.
    for query, param in (
        ("select count(*) from document_chunks where document_id = %s", seeded.doc_a),
        (
            "select count(*) from conversation_documents where conversation_id = %s",
            seeded.conv_a,
        ),
        ("select count(*) from messages where conversation_id = %s", seeded.conv_b),
    ):
        assert _as_role(None, query, (param,))[0][0] == 0
    # B can see the exact seeded message row by id; A cannot.
    assert _as_role(USER_B, "select 1 from messages where id = %s", (seeded.message_b,))
    assert _as_role(USER_A, "select 1 from messages where id = %s", (seeded.message_b,)) == []


def test_matrix_9_retrieval_never_leaks_foreign_chunks(
    client: TestClient, seeded: Seeded
) -> None:
    # A queries retrieval over A's own conversation. B's chunk content must
    # never appear in context (docs/security.md §4, docs/multi-tenancy.md §5).
    response = client.post(
        "/api/v1/rag/query",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
        json={
            "conversation_id": str(seeded.conv_a),
            "question": f"what is the confidentiality rule about {B_MARKER}?",
        },
    )
    assert response.status_code == 200, response.text
    hits = response.json()["hits"]
    if hits:
        assert all(hit["document_id"] == str(seeded.doc_a) for hit in hits)
        assert all(B_MARKER not in hit["content"] for hit in hits)

    # A cannot scope retrieval into B's conversation at all.
    response = client.post(
        "/api/v1/rag/query",
        headers={"Authorization": f"Bearer {_token(USER_A)}"},
        json={
            "conversation_id": str(seeded.conv_b),
            "question": "any question at all",
        },
    )
    assert response.status_code == 404, response.text


class _CountingStorage:
    """Records signed_url invocations around the app's real storage provider."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.sign_count = 0

    async def upload(self, **kwargs) -> None:
        await self.inner.upload(**kwargs)

    async def download(self, **kwargs) -> bytes:
        return await self.inner.download(**kwargs)

    async def delete(self, **kwargs) -> None:
        await self.inner.delete(**kwargs)

    async def signed_url(self, *, key: str, expires_in_seconds: int = 300) -> str:
        self.sign_count += 1
        return await self.inner.signed_url(
            key=key, expires_in_seconds=expires_in_seconds
        )


def test_matrix_10_signed_url_never_issued_for_foreign_document(
    client: TestClient, seeded: Seeded
) -> None:
    app = client.app
    original = app.state.storage_provider
    counting = _CountingStorage(original)
    app.state.storage_provider = counting
    try:
        # Cross-tenant download URL → 404 and the provider never signs.
        response = client.get(
            f"/api/v1/documents/{seeded.doc_b}/download-url",
            headers={"Authorization": f"Bearer {_token(USER_A)}"},
        )
        assert response.status_code == 404, response.text
        assert counting.sign_count == 0

        # Owner path issues a short-lived signed URL (~5 min, docs/api.md §5).
        response = client.get(
            f"/api/v1/documents/{seeded.doc_a}/download-url",
            headers={"Authorization": f"Bearer {_token(USER_A)}"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["url"]
        assert counting.sign_count == 1
        assert body["expires_at"]  # ISO-8601 UTC expiry
        expires_at = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        ttl = (expires_at - datetime.now(timezone.utc)).total_seconds()
        assert 295 <= ttl <= 305
    finally:
        app.state.storage_provider = original