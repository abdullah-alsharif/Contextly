"""Worker pipeline integration matrix (quickstart VS-1..VS-7; docs/testing.md §4).

DB-gated: skipped when DATABASE_URL is unreachable (same pattern as
test_rls.py). Drives pipeline.process_claimed_document directly over the shared
async engine — not the infinite worker loop. Fixture PDFs come from
tests/pdf_fixtures.py (research.md R7). Assertions use an admin psycopg
connection; RLS assertions use SET ROLE contextly_app + claim like test_rls.py.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime
from pathlib import Path

import psycopg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import worker
from app.core.config import Settings
from app.core.security.identity import Identity
from app.providers.storage.base import StorageError
from app.providers.storage.local import LocalStorageProvider
from app.services import pipeline
from app.services.documents import delete_document
from tests.pdf_fixtures import (
    make_corrupt_pdf,
    make_no_text_pdf,
    make_pdf,
    make_poison_pdf,
)

RUNTIME_ROLE = "contextly_app"
LEASE_SECONDS = 300

USER_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_B = uuid.UUID("22222222-2222-2222-2222-222222222222")

_SETTINGS = Settings(
    database_url=os.getenv("DATABASE_URL", "postgresql://localhost/contextly"),
    auth_mode="dev",
    app_env="dev",
    storage_provider="local",
    worker_lease_seconds=LEASE_SECONDS,
    worker_max_retries=3,
    worker_retry_backoff_seconds="1,5,30",
    chunk_size_tokens=500,
    chunk_overlap_tokens=50,
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


def _seed_document(
    *,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    storage_path: str,
    retry_count: int = 0,
) -> None:
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
            cur.execute(
                "insert into documents "
                "(id, user_id, filename, storage_path, file_size_bytes, retry_count) "
                "values (%s, %s, %s, %s, 100, %s)",
                (document_id, user_id, f"{document_id}.pdf", storage_path, retry_count),
            )
        conn.commit()


def _cleanup_document(document_id: uuid.UUID) -> None:
    with _admin() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from document_chunks where document_id = %s", (document_id,))
            cur.execute("delete from documents where id = %s", (document_id,))
            cur.execute("delete from profiles where id in (%s, %s)", (USER_A, USER_B))
        conn.commit()


def _document_row(document_id: uuid.UUID) -> dict:
    with _admin() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, status_error, retry_count, total_chunks, lease_until "
                "from documents where id = %s",
                (document_id,),
            )
            columns = ("status", "status_error", "retry_count", "total_chunks", "lease_until")
            return dict(zip(columns, cur.fetchone(), strict=False))


def _chunk_rows(document_id: uuid.UUID) -> list[tuple]:
    with _admin() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select chunk_index, content, page_number, token_count, metadata "
                "from document_chunks where document_id = %s order by chunk_index",
                (document_id,),
            )
            return cur.fetchall()


async def _run_pipeline(document_id: uuid.UUID, storage: LocalStorageProvider) -> str:
    async with _SessionFactory() as db:
        claimed = await pipeline.claim_next(db, lease_seconds=LEASE_SECONDS)
        assert claimed is not None, "expected a claimable document"
        assert str(claimed.id) == str(document_id)
        await db.commit()
    async with _SessionFactory() as db:
        outcome = await pipeline.process_claimed_document(db, storage, _SETTINGS, claimed)
        if outcome in ("ready", "failed", "retry"):
            await db.commit()
        else:
            await db.rollback()
        return outcome


class _FlakyStorage(LocalStorageProvider):
    """Fails the first `failures` downloads, then delegates to the real provider."""

    def __init__(self, root: Path, failures: int) -> None:
        super().__init__(root=root)
        self.failures = failures

    async def download(self, *, key: str) -> bytes:
        if self.failures > 0:
            self.failures -= 1
            raise StorageError("simulated storage outage")
        return await super().download(key=key)


class _SlowStorage(LocalStorageProvider):
    """Delays every download for `delay` seconds (heartbeat test only)."""

    def __init__(self, root: Path, delay: float) -> None:
        super().__init__(root=root)
        self.delay = delay

    async def download(self, *, key: str) -> bytes:
        await asyncio.sleep(self.delay)
        return await super().download(key=key)


def _lease_until(document_id: uuid.UUID) -> datetime:
    with _admin() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select lease_until from documents where id = %s", (document_id,)
            )
            return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# US1: happy path → ready + page-aware chunks (quickstart VS-1)
# ---------------------------------------------------------------------------


def test_happy_path_produces_page_aware_chunks(tmp_path: Path) -> None:
    document_id = uuid.uuid4()
    storage_path = f"{USER_A}/docs/{document_id}.pdf"
    storage = LocalStorageProvider(root=tmp_path)
    data = make_pdf(
        ["Alpha " * 115 + "page one", "Beta " * 115 + "page two"]
    )
    asyncio.run(storage.upload(key=storage_path, data=data, content_type="application/pdf"))
    _seed_document(document_id=document_id, user_id=USER_A, storage_path=storage_path)

    try:
        outcome = asyncio.run(_run_pipeline(document_id, storage))
        assert outcome == "ready"

        row = _document_row(document_id)
        assert row["status"] == "ready"
        assert row["status_error"] is None
        assert row["lease_until"] is None
        assert row["total_chunks"] == 2

        chunks = _chunk_rows(document_id)
        assert len(chunks) == 2
        assert [c[0] for c in chunks] == [0, 1]
        assert chunks[0][1].startswith("Alpha ") and chunks[0][1].endswith("page one")
        assert chunks[0][2] == 1  # page_number = 1-based start page
        assert chunks[0][4] == {"page_start": 1, "page_end": 1}
        assert chunks[1][1].startswith("Beta ") and chunks[1][1].endswith("page two")
        assert chunks[1][2] == 2
        assert chunks[1][4] == {"page_start": 2, "page_end": 2}
        assert all(c[3] and c[3] > 0 for c in chunks)  # token_count estimated
    finally:
        _cleanup_document(document_id)


def test_chunks_are_tenant_isolated_under_rls(tmp_path: Path) -> None:
    document_id = uuid.uuid4()
    storage_path = f"{USER_A}/docs/{document_id}.pdf"
    storage = LocalStorageProvider(root=tmp_path)
    data = make_pdf(["Private chunk content for user A."])
    asyncio.run(storage.upload(key=storage_path, data=data, content_type="application/pdf"))
    _seed_document(document_id=document_id, user_id=USER_A, storage_path=storage_path)

    try:
        assert asyncio.run(_run_pipeline(document_id, storage)) == "ready"

        conn = _admin()
        try:
            with conn.cursor() as cur:
                cur.execute(f"set role {RUNTIME_ROLE}")
                cur.execute(
                    "select set_config('request.jwt.claim.sub', %s, false)",
                    (str(USER_B),),
                )
                cur.execute(
                    "select count(*) from document_chunks where document_id = %s",
                    (document_id,),
                )
                assert cur.fetchone()[0] == 0
        finally:
            conn.close()

        conn = _admin()
        try:
            with conn.cursor() as cur:
                cur.execute(f"set role {RUNTIME_ROLE}")
                cur.execute(
                    "select set_config('request.jwt.claim.sub', %s, false)",
                    (str(USER_A),),
                )
                cur.execute(
                    "select count(*) from document_chunks where document_id = %s",
                    (document_id,),
                )
                assert cur.fetchone()[0] == 1
        finally:
            conn.close()
    finally:
        _cleanup_document(document_id)


# ---------------------------------------------------------------------------
# US2: failures → retried, then failed (quickstart VS-2, VS-3)
# ---------------------------------------------------------------------------


def test_corrupt_pdf_fails_immediately_without_retry(tmp_path: Path) -> None:
    document_id = uuid.uuid4()
    storage_path = f"{USER_A}/docs/{document_id}.pdf"
    storage = LocalStorageProvider(root=tmp_path)
    asyncio.run(
        storage.upload(
            key=storage_path, data=make_corrupt_pdf(), content_type="application/pdf"
        )
    )
    _seed_document(document_id=document_id, user_id=USER_A, storage_path=storage_path)

    try:
        outcome = asyncio.run(_run_pipeline(document_id, storage))
        assert outcome == "failed"
        row = _document_row(document_id)
        assert row["status"] == "failed"
        assert row["status_error"] == "corrupt or unreadable PDF"
        assert row["retry_count"] == 0
        assert row["lease_until"] is None
        assert _chunk_rows(document_id) == []
    finally:
        _cleanup_document(document_id)


def test_no_text_pdf_fails_with_clear_error(tmp_path: Path) -> None:
    document_id = uuid.uuid4()
    storage_path = f"{USER_A}/docs/{document_id}.pdf"
    storage = LocalStorageProvider(root=tmp_path)
    asyncio.run(
        storage.upload(
            key=storage_path, data=make_no_text_pdf(), content_type="application/pdf"
        )
    )
    _seed_document(document_id=document_id, user_id=USER_A, storage_path=storage_path)

    try:
        outcome = asyncio.run(_run_pipeline(document_id, storage))
        assert outcome == "failed"
        row = _document_row(document_id)
        assert row["status"] == "failed"
        assert "no text extracted" in row["status_error"]
    finally:
        _cleanup_document(document_id)


def _expire_lease(document_id: uuid.UUID) -> None:
    """Simulate the backoff elapsing so the deferred-lease doc is claimable again."""
    with _admin() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update documents set lease_until = now() - interval '1 second' "
                "where id = %s",
                (document_id,),
            )
        conn.commit()


def test_transient_failures_retry_with_backoff_then_fail(tmp_path: Path) -> None:
    document_id = uuid.uuid4()
    storage_path = f"{USER_A}/docs/{document_id}.pdf"
    storage = _FlakyStorage(root=tmp_path, failures=3)
    asyncio.run(
        storage.upload(
            key=storage_path, data=make_pdf(["Recoverable content"]), content_type="application/pdf"
        )
    )
    _seed_document(document_id=document_id, user_id=USER_A, storage_path=storage_path)

    try:
        outcome = asyncio.run(_run_pipeline(document_id, storage))
        assert outcome == "retry"
        row = _document_row(document_id)
        assert row["status"] == "uploaded"
        assert row["retry_count"] == 1
        assert row["lease_until"] is not None  # deferred per backoff

        async def second_attempt() -> str:
            async with _SessionFactory() as db:
                claimed = await pipeline.claim_next(db, lease_seconds=LEASE_SECONDS)
                assert claimed is None, "deferred lease must not be re-claimable yet"
            return "skipped"

        assert asyncio.run(second_attempt()) == "skipped"
        _expire_lease(document_id)

        outcome = asyncio.run(_run_pipeline(document_id, storage))
        assert outcome == "retry"
        row = _document_row(document_id)
        assert row["retry_count"] == 2
        _expire_lease(document_id)

        outcome = asyncio.run(_run_pipeline(document_id, storage))
        assert outcome == "failed"
        row = _document_row(document_id)
        assert row["status"] == "failed"
        assert row["retry_count"] == 3
        assert row["status_error"]
        assert row["lease_until"] is None
        assert _chunk_rows(document_id) == []
    finally:
        _cleanup_document(document_id)


# ---------------------------------------------------------------------------
# US2: unexpected exceptions are isolated (convergence T024 — poison PDFs)
# ---------------------------------------------------------------------------


def test_poison_pdf_is_isolated_retried_then_failed(tmp_path: Path) -> None:
    """A PDF that crashes pypdf's extract_text must not kill the worker loop.

    The KeyError escapes parse_pdf as an unexpected exception; the pipeline
    catches it, treats it as transient (backoff + retry_count), and exhausts
    into failed — never letting the exception reach the caller.
    """
    document_id = uuid.uuid4()
    storage_path = f"{USER_A}/docs/{document_id}.pdf"
    storage = LocalStorageProvider(root=tmp_path)
    asyncio.run(
        storage.upload(
            key=storage_path, data=make_poison_pdf(), content_type="application/pdf"
        )
    )
    _seed_document(document_id=document_id, user_id=USER_A, storage_path=storage_path)

    try:
        outcome = asyncio.run(_run_pipeline(document_id, storage))
        assert outcome == "retry"
        row = _document_row(document_id)
        assert row["status"] == "uploaded"
        assert row["retry_count"] == 1
        assert "unexpected" in row["status_error"]
        assert row["lease_until"] is not None
        assert _chunk_rows(document_id) == []

        _expire_lease(document_id)
        outcome = asyncio.run(_run_pipeline(document_id, storage))
        assert outcome == "retry"
        assert _document_row(document_id)["retry_count"] == 2

        _expire_lease(document_id)
        outcome = asyncio.run(_run_pipeline(document_id, storage))
        assert outcome == "failed"
        row = _document_row(document_id)
        assert row["status"] == "failed"
        assert row["retry_count"] == 3
        assert "unexpected" in row["status_error"]
        assert row["lease_until"] is None
        assert _chunk_rows(document_id) == []
    finally:
        _cleanup_document(document_id)


# ---------------------------------------------------------------------------
# US3: exactly one worker per document (quickstart VS-4, VS-5)
# ---------------------------------------------------------------------------


def test_concurrent_claim_has_single_winner(tmp_path: Path) -> None:
    document_id = uuid.uuid4()
    storage_path = f"{USER_A}/docs/{document_id}.pdf"
    storage = LocalStorageProvider(root=tmp_path)
    data = make_pdf(["One document, two would-be workers."])
    asyncio.run(storage.upload(key=storage_path, data=data, content_type="application/pdf"))
    _seed_document(document_id=document_id, user_id=USER_A, storage_path=storage_path)

    try:
        async def claim_once() -> str | None:
            async with _SessionFactory() as db:
                claimed = await pipeline.claim_next(db, lease_seconds=LEASE_SECONDS)
                await db.commit()
                return None if claimed is None else str(claimed.id)

        async def claim_both() -> list[str | None]:
            return await asyncio.gather(claim_once(), claim_once())

        results = asyncio.run(claim_both())
        winners = [result for result in results if result is not None]
        assert len(winners) == 1
        assert winners[0] == str(document_id)

        row = _document_row(document_id)
        assert row["status"] == "processing"
        assert row["lease_until"] is not None
    finally:
        _cleanup_document(document_id)


def test_heartbeat_rearms_lease_mid_run(tmp_path: Path) -> None:
    """US3/AC4: a slow download outlasting the interval must have its lease re-armed.

    Lease = 12s → heartbeat interval = 4s; the slow storage stalls the download
    for 10s. If no heartbeat ran, lease_until stays at claim time + 12s; after
    the first re-arm it jumps to re-arm time + 12s. We read mid-processing —
    strictly after the first interval, strictly before finalize clears the lease.
    """
    heartbeat_lease = 12
    download_delay = 10.0
    hb_settings = _SETTINGS.model_copy(update={"worker_lease_seconds": heartbeat_lease})

    document_id = uuid.uuid4()
    storage_path = f"{USER_A}/docs/{document_id}.pdf"
    storage = _SlowStorage(root=tmp_path, delay=download_delay)
    asyncio.run(
        storage.upload(
            key=storage_path, data=make_pdf(["Slow page."]), content_type="application/pdf"
        )
    )
    _seed_document(document_id=document_id, user_id=USER_A, storage_path=storage_path)

    try:
        async def scenario() -> tuple[str, datetime, datetime]:
            async with _SessionFactory() as db:
                claimed = await pipeline.claim_next(
                    db, lease_seconds=heartbeat_lease
                )
                assert claimed is not None
                await db.commit()
            initial_lease = _lease_until(document_id)

            stop = asyncio.Event()
            heartbeat = asyncio.create_task(
                worker._heartbeat(hb_settings, claimed, stop, _SessionFactory)
            )
            try:
                async with _SessionFactory() as db:
                    process = asyncio.create_task(
                        pipeline.process_claimed_document(db, storage, hb_settings, claimed)
                    )
                    await asyncio.sleep(heartbeat_lease / 3 + 2.0)
                    mid_run_lease = _lease_until(document_id)
                    outcome = await process
                    await db.commit()
            finally:
                stop.set()
                heartbeat.cancel()
                try:
                    await heartbeat
                except asyncio.CancelledError:
                    pass
            return outcome, initial_lease, mid_run_lease

        outcome, initial_lease, mid_run_lease = asyncio.run(scenario())

        assert outcome == "ready"
        assert mid_run_lease > initial_lease  # re-armed strictly after the first interval
    finally:
        _cleanup_document(document_id)


def test_live_lease_is_not_stolen_and_expired_lease_is_reclaimed(tmp_path: Path) -> None:
    document_id = uuid.uuid4()
    storage_path = f"{USER_A}/docs/{document_id}.pdf"
    storage = LocalStorageProvider(root=tmp_path)
    data = make_pdf(["Lease mechanics."])
    asyncio.run(storage.upload(key=storage_path, data=data, content_type="application/pdf"))
    _seed_document(document_id=document_id, user_id=USER_A, storage_path=storage_path)

    try:
        async def claim_once() -> str | None:
            async with _SessionFactory() as db:
                claimed = await pipeline.claim_next(db, lease_seconds=LEASE_SECONDS)
                await db.commit()
                return None if claimed is None else str(claimed.id)

        assert asyncio.run(claim_once()) == str(document_id)

        async def claim_again() -> str | None:
            async with _SessionFactory() as db:
                claimed = await pipeline.claim_next(db, lease_seconds=LEASE_SECONDS)
                await db.commit()
                return None if claimed is None else str(claimed.id)

        assert asyncio.run(claim_again()) is None  # live lease → no steal

        with _admin() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update documents set lease_until = now() - interval '1 second' "
                    "where id = %s",
                    (document_id,),
                )
            conn.commit()

        assert asyncio.run(claim_again()) == str(document_id)  # expired → re-claimed
    finally:
        _cleanup_document(document_id)


# ---------------------------------------------------------------------------
# US4: delete purges chunks (quickstart VS-6)
# ---------------------------------------------------------------------------


def test_delete_purges_chunks_and_worker_writes_nothing_after(tmp_path: Path) -> None:
    document_id = uuid.uuid4()
    storage_path = f"{USER_A}/docs/{document_id}.pdf"
    storage = LocalStorageProvider(root=tmp_path)
    data = make_pdf(["Will be deleted, chunks must vanish."])
    asyncio.run(storage.upload(key=storage_path, data=data, content_type="application/pdf"))
    _seed_document(document_id=document_id, user_id=USER_A, storage_path=storage_path)

    try:
        assert asyncio.run(_run_pipeline(document_id, storage)) == "ready"
        assert len(_chunk_rows(document_id)) == 1

        async def delete_as_owner() -> None:
            async with _SessionFactory() as db:
                await delete_document(
                    db,
                    storage,
                    Identity(user_id=USER_A),
                    document_id,
                )
                await db.commit()

        asyncio.run(delete_as_owner())

        assert _chunk_rows(document_id) == []
        with _admin() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "select deleted_at from documents where id = %s", (document_id,)
                )
                assert cur.fetchone()[0] is not None

        async def try_claim() -> str | None:
            async with _SessionFactory() as db:
                claimed = await pipeline.claim_next(db, lease_seconds=LEASE_SECONDS)
                await db.commit()
                return None if claimed is None else str(claimed.id)

        assert asyncio.run(try_claim()) is None  # deleted rows are never claimable
        assert _chunk_rows(document_id) == []  # worker wrote nothing for a deleted doc
    finally:
        _cleanup_document(document_id)


def test_delete_during_processing_persists_no_chunks(tmp_path: Path) -> None:
    document_id = uuid.uuid4()
    storage_path = f"{USER_A}/docs/{document_id}.pdf"
    storage = LocalStorageProvider(root=tmp_path)
    data = make_pdf(["Deleted mid-flight; chunks must never appear."])
    asyncio.run(storage.upload(key=storage_path, data=data, content_type="application/pdf"))
    _seed_document(document_id=document_id, user_id=USER_A, storage_path=storage_path)

    try:
        async def claim_document() -> pipeline.ClaimedDocument:
            async with _SessionFactory() as db:
                claimed = await pipeline.claim_next(db, lease_seconds=LEASE_SECONDS)
                assert claimed is not None
                await db.commit()
                return claimed

        claimed = asyncio.run(claim_document())

        with _admin() as conn:  # delete the row mid-flight, keep the storage file
            with conn.cursor() as cur:
                cur.execute(
                    "update documents set deleted_at = now() where id = %s",
                    (document_id,),
                )
            conn.commit()

        async def run_against_stale_claim() -> str:
            async with _SessionFactory() as db:
                outcome = await pipeline.process_claimed_document(
                    db, storage, _SETTINGS, claimed
                )
                await db.rollback()
                return outcome

        outcome = asyncio.run(run_against_stale_claim())

        assert outcome == "stale"
        assert _chunk_rows(document_id) == []
    finally:
        _cleanup_document(document_id)
