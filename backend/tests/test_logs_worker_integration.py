"""Action-log events from the processing pipeline (specs/016 US1, FR-002).

DB-gated (same pattern as test_worker_integration.py). Drives
pipeline.process_claimed_document directly and asserts the action_logs rows
each outcome must emit: a corrupt PDF → 'processing_started' +
'processing_failed' (with reason + trace); a valid PDF → 'processing_started' +
'processing_succeeded'; a transient failure followed by success →
'processing_started' ×2 + 'processing_succeeded' and never 'processing_failed'.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any

import psycopg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.providers.ai import build_ai_provider
from app.providers.ai.base import AIProvider
from app.providers.storage.base import StorageError
from app.providers.storage.local import LocalStorageProvider
from app.services import pipeline
from tests.pdf_fixtures import make_corrupt_pdf, make_pdf

LEASE_SECONDS = 300

USER_A = uuid.UUID("11111111-1111-1111-1111-111111111111")

_SETTINGS = Settings(
    database_url=os.getenv("DATABASE_URL", "postgresql://localhost/contextly"),
    auth_mode="dev",
    app_env="dev",
    storage_provider="local",
    worker_lease_seconds=LEASE_SECONDS,
    worker_max_retries=3,
    worker_retry_backoff_seconds="1,5,30",
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


def _seed_document(
    *, document_id: uuid.UUID, storage_path: str, filename: str | None = None
) -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into auth.users (id) values (%s) on conflict (id) do nothing",
                (USER_A,),
            )
            cur.execute(
                "insert into profiles (id, email) values (%s, %s) "
                "on conflict (id) do nothing",
                (USER_A, f"{USER_A}@example.com"),
            )
            cur.execute(
                "insert into documents "
                "(id, user_id, filename, storage_path, file_size_bytes) "
                "values (%s, %s, %s, %s, 100)",
                (document_id, USER_A, filename or f"{document_id}.pdf", storage_path),
            )
        conn.commit()


def _cleanup(*document_ids: uuid.UUID) -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            ids = [str(i) for i in document_ids]
            cur.execute(
                "delete from document_chunks where document_id = any(%s)", (ids,)
            )
            cur.execute("delete from action_logs where document_id = any(%s)", (ids,))
            cur.execute(
                "update documents set replaces_document_id = null "
                "where replaces_document_id = any(%s)",
                (ids,),
            )
            cur.execute("delete from documents where id = any(%s)", (ids,))
            cur.execute("delete from profiles where id = %s", (USER_A,))
        conn.commit()


def _log_rows(document_id: uuid.UUID) -> list[tuple[Any, ...]]:
    """(action_type, outcome, error_message, error_trace, metadata) newest first."""
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select action_type, outcome, error_message, error_trace, metadata "
                "from action_logs where document_id = %s "
                "order by created_at asc, id asc",
                (document_id,),
            )
            return cur.fetchall()


def _fake_ai() -> AIProvider:
    return build_ai_provider(_SETTINGS)


async def _run_pipeline(document_id: uuid.UUID, storage: LocalStorageProvider) -> str:
    async with _SessionFactory() as db:
        claimed = await pipeline.claim_next(db, lease_seconds=LEASE_SECONDS)
        assert claimed is not None, "expected a claimable document"
        assert str(claimed.id) == str(document_id)
        await db.commit()
    async with _SessionFactory() as db:
        outcome = await pipeline.process_claimed_document(
            db, storage, _SETTINGS, claimed, _fake_ai()
        )
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


# ---------------------------------------------------------------------------
# US1 recording: pipeline outcomes → action_logs rows
# ---------------------------------------------------------------------------


def test_corrupt_pdf_logs_started_and_failed(tmp_path: Path) -> None:
    document_id = uuid.uuid4()
    storage_path = f"{USER_A}/docs/{document_id}.pdf"
    storage = LocalStorageProvider(root=tmp_path)
    asyncio.run(
        storage.upload(
            key=storage_path, data=make_corrupt_pdf(), content_type="application/pdf"
        )
    )
    _seed_document(document_id=document_id, storage_path=storage_path)

    try:
        assert asyncio.run(_run_pipeline(document_id, storage)) == "failed"
        rows = _log_rows(document_id)
        assert [r[0] for r in rows] == ["processing_started", "processing_failed"]
        assert rows[0][1] == "succeeded" and rows[0][2] is None
        failed = rows[1]
        assert failed[1] == "failed"
        assert failed[2] == "corrupt or unreadable PDF"
        assert failed[3] and "ParseError" in failed[3]  # trace captured
        assert failed[4] == {"retry_count": 0}
    finally:
        _cleanup(document_id)


def test_valid_pdf_logs_started_and_succeeded(tmp_path: Path) -> None:
    document_id = uuid.uuid4()
    storage_path = f"{USER_A}/docs/{document_id}.pdf"
    storage = LocalStorageProvider(root=tmp_path)
    asyncio.run(
        storage.upload(
            key=storage_path, data=make_pdf(["Hello chunk"]), content_type="application/pdf"
        )
    )
    _seed_document(document_id=document_id, storage_path=storage_path)

    try:
        assert asyncio.run(_run_pipeline(document_id, storage)) == "ready"
        rows = _log_rows(document_id)
        assert [r[0] for r in rows] == ["processing_started", "processing_succeeded"]
        assert rows[0][1] == "succeeded"
        done = rows[1]
        assert done[1] == "succeeded"
        assert done[2] is None and done[3] is None
        assert done[4]["total_chunks"] == 1
    finally:
        _cleanup(document_id)


def test_transient_failure_then_success_logs_two_starts_no_failure(tmp_path: Path) -> None:
    document_id = uuid.uuid4()
    storage_path = f"{USER_A}/docs/{document_id}.pdf"
    storage = _FlakyStorage(root=tmp_path, failures=1)
    asyncio.run(
        storage.upload(
            key=storage_path, data=make_pdf(["Retry content"]), content_type="application/pdf"
        )
    )
    _seed_document(document_id=document_id, storage_path=storage_path)

    try:
        assert asyncio.run(_run_pipeline(document_id, storage)) == "retry"
        assert [r[0] for r in _log_rows(document_id)] == ["processing_started"]

        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update documents set lease_until = now() - interval '1 second' "
                    "where id = %s",
                    (document_id,),
                )
            conn.commit()

        assert asyncio.run(_run_pipeline(document_id, storage)) == "ready"
        rows = _log_rows(document_id)
        assert [r[0] for r in rows] == [
            "processing_started",
            "processing_started",
            "processing_succeeded",
        ]
        assert all(r[1] == "succeeded" for r in rows)
    finally:
        _cleanup(document_id)


def test_replace_fail_restore_cycle_logs_restored(tmp_path: Path) -> None:
    """T012: replacing a doc, then failing the replacement, restores the old row
    and logs the full cycle: upload → upload → replace → superseded →
    processing_started → restored → processing_failed (the restored event fires
    during the same UPDATE that fails the replacement)."""
    old_id, new_id = uuid.uuid4(), uuid.uuid4()
    old_path = f"{USER_A}/docs/{old_id}.pdf"
    new_path = f"{USER_A}/docs/{new_id}.pdf"
    storage = LocalStorageProvider(root=tmp_path)
    asyncio.run(
        storage.upload(
            key=old_path, data=make_pdf(["Original"]), content_type="application/pdf"
        )
    )
    asyncio.run(
        storage.upload(
            key=new_path, data=make_pdf(["Replacement"]), content_type="application/pdf"
        )
    )
    _seed_document(document_id=old_id, storage_path=old_path, filename="cycle.pdf")
    # replace: the old row must leave the active set before the new insert
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update documents set status = 'superseded', superseded_from = 'uploaded' "
                "where id = %s",
                (old_id,),
            )
        conn.commit()
    _seed_document(document_id=new_id, storage_path=new_path, filename="cycle.pdf")
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update documents set replaces_document_id = %s where id = %s",
                (old_id, new_id),
            )
        conn.commit()

    # fail the replacement through the worker: corrupt its bytes on disk
    asyncio.run(
        storage.upload(
            key=new_path, data=make_corrupt_pdf(), content_type="application/pdf"
        )
    )
    try:
        assert asyncio.run(_run_pipeline(new_id, storage)) == "failed"
        assert [r[0] for r in _log_rows(new_id)] == [
            "processing_started",
            "processing_failed",
        ]
        restored = _log_rows(old_id)
        assert [r[0] for r in restored] == ["restored"]
        assert restored[0][1] == "succeeded" and restored[0][2] is None
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "select status, superseded_from from documents where id = %s",
                    (old_id,),
                )
                assert cur.fetchone() == ("uploaded", None)
    finally:
        _cleanup(old_id, new_id)
