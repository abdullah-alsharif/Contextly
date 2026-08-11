"""Shared test harness for the Phase 9 security suite (tests/security/).

The project's DB-gated pattern (test_documents_api.py) keeps each test file
self-contained; the security suite has four files that would otherwise each
carry ~25 lines of identical engine/skip/client wiring, so it is centralized
here instead. Runtime behavior is identical to the per-file pattern: a fresh
NullPool async engine + session factory per client, DB-gated skip, local storage
in a tmp dir, dev auth, and high rate-limit budgets unless overridden.
"""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.security.dev import dev_token
from app.db.session import get_db
from app.main import create_app

DEV_SECRET = "contextly-dev-secret-0123456789abcdef"
MAX_UPLOAD = 10 * 1024 * 1024

USER_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def database_url() -> str:
    """The test DATABASE_URL (only meaningful when DB_GATE tests run)."""
    return os.environ["DATABASE_URL"]


def database_reachable() -> bool:
    url = os.getenv("DATABASE_URL")
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=1) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


DB_GATE = pytest.mark.skipif(not database_reachable(), reason="DATABASE_URL not reachable")


def token(user: uuid.UUID, *, secret: str = DEV_SECRET) -> str:
    """Dev-mode JWT for the given user (specs/003-jwt-authentication)."""
    return dev_token(user, secret=secret)


def make_client(
    storage_dir: str,
    *,
    general_budget: int = 1_000_000,
    chat_budget: int = 1_000_000,
    **settings_overrides,
) -> TestClient:
    """Build an app with a per-call NullPool engine and local storage.

    session_factory is the test engine (NullPool) — the chat path
    (prepare_chat) opens its own sessions, and the default module engine is
    pooled and loop-bound (test_chat_api.py:90 pattern). Budgets default to
    effectively-unlimited so tests exercise isolation, not throttling; override
    with `general_budget`/`chat_budget` for the rate-limit tests.
    """
    engine = create_async_engine(
        os.getenv("DATABASE_URL", "postgresql://localhost/contextly").replace(
            "postgresql://", "postgresql+asyncpg://", 1
        ),
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    settings = Settings(
        database_url=os.environ["DATABASE_URL"],
        auth_mode="dev",
        app_env="dev",
        dev_jwt_secret=DEV_SECRET,
        storage_provider="local",
        local_storage_dir=str(storage_dir),
        upload_max_bytes=MAX_UPLOAD,
        rate_limit_general_per_minute=general_budget,
        rate_limit_chat_per_minute=chat_budget,
        **settings_overrides,
    )

    async def get_test_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app = create_app(settings=settings, session_factory=session_factory)
    app.dependency_overrides[get_db] = get_test_db
    return TestClient(app)