"""API-level auth tests (quickstart VS-2; docs/testing.md §2 auth group).

DB-gated: skipped when DATABASE_URL is unreachable (same pattern as test_rls.py).
Covers contracts/auth.md §6: /api/v1/auth/me with dev tokens — provisioning on
first sight (idempotent), 401 matrix (missing/malformed/expired/wrong-secret/
wrong-audience), healthz stays open, WWW-Authenticate header present.
"""
from __future__ import annotations

import os
import time
import uuid

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.security.dev import DEV_AUDIENCE, DevAuthenticator, dev_token
from app.core.security.deps import build_authenticator
from app.main import create_app

DEV_SECRET = "contextly-dev-secret-0123456789abcdef"
SUB = uuid.uuid4()


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


@pytest.fixture(scope="module")
def client() -> TestClient:
    settings = Settings(
        database_url=os.environ["DATABASE_URL"],
        auth_mode="dev",
        app_env="dev",
        dev_jwt_secret=DEV_SECRET,
    )
    app = create_app(settings=settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def cleanup() -> None:
    yield
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("delete from profiles where id = %s", (SUB,))
        conn.commit()


def test_auth_me_provisions_profile_on_first_call(
    client: TestClient, cleanup: None
) -> None:
    token = dev_token(SUB, secret=DEV_SECRET, email="api-test@dev.contextly.local")
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(SUB)
    assert body["email"] == "api-test@dev.contextly.local"
    assert body["full_name"] is None

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("select email from profiles where id = %s", (SUB,))
            assert cur.fetchone() == ("api-test@dev.contextly.local",)


def test_auth_me_is_idempotent(client: TestClient, cleanup: None) -> None:
    for _ in range(2):
        token = dev_token(SUB, secret=DEV_SECRET)
        response = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from profiles where id = %s", (SUB,))
            assert cur.fetchone()[0] == 1


def test_auth_me_rls_isolation_through_request_session(client: TestClient) -> None:
    """T029 / US2 AC4 / FR-007: the request session runs under contextly_app
    with the caller's claim — user A sees A's profile, never user B's.

    Proves RLS through the exact machinery `/auth/me` uses: the real
    get_current_user dependency driving a real SQLAlchemy async session,
    then a query for another tenant's profile returns nothing.
    """
    import asyncio

    from fastapi.security import HTTPAuthorizationCredentials
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.security.deps import get_current_user

    user_b = uuid.uuid4()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute("insert into auth.users (id) values (%s)", (user_b,))
            cur.execute(
                "insert into profiles (id, email) values (%s, %s)",
                (user_b, "b@example.com"),
            )
        conn.commit()
    try:
        token_b = dev_token(user_b, secret=DEV_SECRET, email="b@example.com")
        response_b = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token_b}"}
        )
        assert response_b.status_code == 200
        assert response_b.json()["id"] == str(user_b)

        token_a = dev_token(SUB, secret=DEV_SECRET)
        response_a = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token_a}"}
        )
        assert response_a.status_code == 200
        assert response_a.json()["id"] == str(SUB)

        async def probe() -> tuple[int, int]:
            # Fresh engine: the module-scoped TestClient owns its own loop, so
            # pool connections from its loop cannot be reused in this loop.
            engine = create_async_engine(
                os.environ["DATABASE_URL"].replace(
                    "postgresql://", "postgresql+asyncpg://", 1
                )
            )
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    credentials = HTTPAuthorizationCredentials(
                        scheme="Bearer", credentials=token_a
                    )
                    agen = get_current_user(
                        credentials=credentials,
                        db=session,
                        settings=Settings(),
                    )
                    identity = await agen.__anext__()
                    assert identity.user_id == SUB

                    a_rows = (
                        await session.execute(
                            text("select count(*) from profiles where id = :uid"),
                            {"uid": str(SUB)},
                        )
                    ).scalar_one()
                    b_rows = (
                        await session.execute(
                            text("select count(*) from profiles where id = :uid"),
                            {"uid": str(user_b)},
                        )
                    ).scalar_one()

                    with pytest.raises(StopAsyncIteration):
                        await agen.__anext__()
                    return int(a_rows), int(b_rows)
            finally:
                await engine.dispose()

        a_rows, b_rows = asyncio.run(probe())
        assert a_rows == 1, "A's own profile must be visible"
        assert b_rows == 0, "B's profile must be invisible under A's identity"
    finally:
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                cur.execute("delete from profiles where id = %s", (user_b,))
            conn.commit()


def test_auth_me_missing_token_401(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_auth_me_wrong_scheme_401(client: TestClient) -> None:
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Basic dXNlcjpwYXNz"}
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_auth_me_malformed_token_401(client: TestClient) -> None:
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_auth_me_expired_token_401(client: TestClient) -> None:
    token = dev_token(SUB, secret=DEV_SECRET, expires_in_seconds=-3600)
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_auth_me_wrong_secret_401(client: TestClient) -> None:
    token = dev_token(SUB, secret="not-the-configured-secret-0123456789")
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_auth_me_wrong_audience_401(client: TestClient) -> None:
    token = jwt.encode(
        {
            "sub": str(SUB),
            "aud": "something-else",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        },
        DEV_SECRET,
        algorithm="HS256",
    )
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_healthz_open_without_token(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200


def test_build_authenticator_selects_dev_mode() -> None:
    settings = Settings(auth_mode="dev", app_env="dev", dev_jwt_secret=DEV_SECRET)
    auth = build_authenticator(settings)
    assert isinstance(auth, DevAuthenticator)
    identity = auth.authenticate(dev_token(SUB, secret=DEV_SECRET))
    assert identity.user_id == SUB


def test_dev_token_audience_is_dev() -> None:
    assert DEV_AUDIENCE == "contextly-dev"
