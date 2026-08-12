"""DB-backed worker: poll for claims, process documents (docs/ingestion.md §3).

The Postgres table is the queue (no external broker). One worker process runs
in compose; `for update skip locked` in worker_claim_next keeps concurrent
workers safe if one is ever added. Each document gets its own DB session
(research.md R6); a background heartbeat re-arms the claim lease every
min(lease_seconds/3, 30)s so slow parses aren't re-claimed (contracts §3).
"""

from __future__ import annotations

import asyncio
import logging
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.db.session import SessionFactory
from app.providers.ai import build_ai_provider
from app.providers.ai.base import AIProvider
from app.providers.storage import build_storage_provider
from app.providers.storage.base import StorageProvider
from app.services import pipeline

logger = logging.getLogger(__name__)

SessionFactoryType = async_sessionmaker[AsyncSession]


async def _heartbeat(
    settings: Settings,
    claimed: pipeline.ClaimedDocument,
    stop: asyncio.Event,
    session_factory: SessionFactoryType = SessionFactory,
) -> None:
    """Re-arm the lease in its own committed transaction until the doc is done."""
    interval = min(settings.worker_lease_seconds / 3, 30)
    while not stop.is_set():
        await asyncio.sleep(interval)
        try:
            async with session_factory() as db:
                await pipeline.rearm_lease(db, claimed, settings.worker_lease_seconds)
                await db.commit()
        except Exception:
            logger.exception(
                "lease heartbeat failed for doc %s (lease may lapse)",
                claimed.id,
            )


async def _process_one(
    settings: Settings, storage: StorageProvider, ai: AIProvider
) -> tuple[bool, pipeline.Outcome | None]:
    """Claim and process a single document. Returns (claimed, outcome)."""
    async with SessionFactory() as db:
        claimed = await pipeline.claim_next(
            db, lease_seconds=settings.worker_lease_seconds
        )
        if claimed is None:
            return False, None
        await db.commit()

    started = perf_counter()
    logger.info(
        "doc %s claimed | stage=claim | retry_count=%d", claimed.id, claimed.retry_count
    )
    stop = asyncio.Event()
    heartbeat = asyncio.create_task(_heartbeat(settings, claimed, stop))
    try:
        async with SessionFactory() as db:
            outcome = await pipeline.process_claimed_document(
                db, storage, settings, claimed, ai
            )
            if outcome in ("ready", "failed", "retry"):
                await db.commit()
            else:
                await db.rollback()
        logger.info(
            "doc %s finished | outcome=%s | duration_ms=%.0f",
            claimed.id,
            outcome,
            (perf_counter() - started) * 1000,
        )
        return True, outcome
    finally:
        stop.set()
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass


async def _run(settings: Settings) -> None:
    storage = build_storage_provider(settings)
    ai = build_ai_provider(settings)
    logger.info(
        "worker starting | ai_provider=%s embedding_model=%s embedding_dims=%d "
        "storage_provider=%s poll_interval=%ss lease=%ss",
        settings.ai_provider,
        ai.embedding_model,
        ai.embedding_dims,
        settings.storage_provider,
        settings.worker_poll_interval_seconds,
        settings.worker_lease_seconds,
    )
    while True:
        claimed, outcome = await _process_one(settings, storage, ai)
        if not claimed:
            await asyncio.sleep(settings.worker_poll_interval_seconds)
        elif outcome == "retry":
            await asyncio.sleep(settings.worker_poll_interval_seconds)


def run() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    try:
        asyncio.run(_run(settings))
    except KeyboardInterrupt:
        logger.info("worker stopping (SIGINT)")


if __name__ == "__main__":
    run()
