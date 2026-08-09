"""Async SQLAlchemy engine (Phase 1).

The async dialect (postgresql+asyncpg) is derived from the plain postgresql://
DATABASE_URL at the engine layer per docs/local-dev.md §3 — the env var keeps a
single scheme, shared with the sync psycopg migrations runner and health probe.
"""
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

_settings = get_settings()
_async_database_url = _settings.database_url.replace(
    "postgresql://", "postgresql+asyncpg://", 1
)

engine = create_async_engine(_async_database_url)
