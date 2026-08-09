"""Async session factory + FastAPI dependency (Phase 1).

Contracts: specs/002-database-schema/contracts/database.md §4.
"""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.engine import engine

SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield one AsyncSession per request, always closed afterwards."""
    async with SessionFactory() as session:
        yield session
