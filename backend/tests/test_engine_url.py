"""Offline unit tests for the async engine URL/connect-args derivation.

No database, no network (docs/testing.md §1): validates the sslmode →
asyncpg ssl translation that keeps a shared postgresql:// DATABASE_URL usable
by both psycopg (sync: migrations, health probe) and asyncpg (SQLAlchemy).
"""

from __future__ import annotations

from app.db.engine import async_url_and_args


def test_sslmode_require_translates_to_asyncpg_ssl() -> None:
    url, args = async_url_and_args(
        "postgresql://u:p@host:5432/db?sslmode=require&application_name=x"
    )
    assert args == {"ssl": "require"}
    assert url == "postgresql+asyncpg://u:p@host:5432/db?application_name=x"


def test_sslmode_verify_full() -> None:
    url, args = async_url_and_args(
        "postgresql://u:p@host:5432/db?sslmode=verify-full"
    )
    assert args == {"ssl": "verify-full"}
    assert url == "postgresql+asyncpg://u:p@host:5432/db"


def test_sslmode_disable_maps_to_false() -> None:
    _, args = async_url_and_args("postgresql://u:p@host/db?sslmode=disable")
    assert args == {"ssl": False}


def test_no_sslmode_defaults_to_no_ssl_arg() -> None:
    url, args = async_url_and_args("postgresql://u:p@host/db")
    assert args == {}
    assert url == "postgresql+asyncpg://u:p@host/db"


def test_other_query_params_preserved() -> None:
    url, args = async_url_and_args(
        "postgresql://u:p@host/db?sslmode=require&connect_timeout=10"
    )
    assert args == {"ssl": "require"}
    assert url == "postgresql+asyncpg://u:p@host/db?connect_timeout=10"