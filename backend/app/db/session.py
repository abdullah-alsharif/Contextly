"""Async session factory + FastAPI dependency (Phase 1).

Contracts: specs/002-database-schema/contracts/database.md §4.
"""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.engine import engine

SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield one AsyncSession per request; commit on success, rollback otherwise.

    The whole request runs in a single transaction so the RLS `SET LOCAL ROLE
    contextly_app` + claim set by get_current_user stay transaction-local and
    are discarded on rollback/commit (docs/multi-tenancy.md §2). The commit also
    persists profile bootstrapping from ensure_profile.
    """
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
