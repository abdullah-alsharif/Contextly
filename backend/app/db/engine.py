"""Async SQLAlchemy engine (Phase 1).

The async dialect (postgresql+asyncpg) is derived from the plain postgresql://
DATABASE_URL at the engine layer per docs/local-dev.md §3 — the env var keeps a
single scheme, shared with the sync psycopg migrations runner and health probe.

asyncpg has no `sslmode` connect parameter and SQLAlchemy forwards URL query
params as connect kwargs, so a DATABASE_URL carrying `?sslmode=require`
(Supabase, docs/deployment.md §3) would crash every async connection. The
sslmode value is translated to asyncpg's `ssl` argument instead; psycopg (sync)
keeps reading it from the same URL untouched.
"""

from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

# sslmode (psycopg vocabulary) → asyncpg ssl argument. `prefer`/absent are
# left out (asyncpg's default, no SSL), matching local dev's plaintext compose
# Postgres.
_SSLMODE_TO_SSL: dict[str, object] = {
    "disable": False,
    "require": "require",
    "verify-ca": "verify-full",
    "verify-full": "verify-full",
}


def async_url_and_args(database_url: str) -> tuple[str, dict[str, object]]:
    """Split sslmode off a postgresql:// URL into asyncpg connect kwargs."""
    parts = urlsplit(database_url)
    query = parse_qs(parts.query)
    sslmode = query.pop("sslmode", ["prefer"])[0]
    connect_args: dict[str, object] = {}
    ssl = _SSLMODE_TO_SSL.get(sslmode)
    if ssl is not None:
        connect_args["ssl"] = ssl
    url = urlunsplit(
        (
            parts.scheme + "+asyncpg",
            parts.netloc,
            parts.path,
            urlencode(query, doseq=True),
            parts.fragment,
        )
    )
    return url, connect_args


_settings = get_settings()
_async_database_url, _async_connect_args = async_url_and_args(_settings.database_url)

engine = create_async_engine(_async_database_url, connect_args=_async_connect_args)