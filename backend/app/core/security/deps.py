"""Shared auth dependencies guarding /api/v1 business routes.

`get_current_user` (contracts/auth.md §1, §4):
1. Parse `Authorization: Bearer <JWT>`.
2. Verify with the mode-selected authenticator (dev or Supabase).
3. Any failure → 401 (never 200).
4. On success, switch the request's DB session transaction-locally to the
   NOBYPASSRLS `contextly_app` role and set the user's claim, so every query
   in the request runs under RLS (docs/multi-tenancy.md §2) — the app never
   bypasses the database boundary.
5. Bootstrap the user's `profiles` row if missing (docs/security.md §1).

`get_current_user_streaming` — the same 1-3, for routes that return a STREAMED
response body (SSE chat send, document download). FastAPI keeps yield-
dependency sessions open until the response body finishes, so a request
session would stay in an open transaction for the whole stream and its
profiles UPSERT would hold a row lock that blocks every concurrent request
(docs/chat.md §4). This variant never opens a request-scoped session — the
bootstrap runs on a short-lived session that COMMITS immediately, so the
stream holds zero DB connections. Routes that still query a `db` session
(document download) apply the RLS role/claim explicitly via
`apply_identity_to_session`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.security.base import AuthError, Authenticator
from app.core.security.dev import DevAuthenticator
from app.core.security.identity import Identity
from app.core.security.supabase import SupabaseAuthenticator
from app.db.session import get_db
from app.services.profiles import ensure_profile

_bearer = HTTPBearer(auto_error=False)

RLS_ROLE = "contextly_app"


async def apply_identity_to_session(db: AsyncSession, identity: Identity) -> None:
    """Switch a DB session to the NOBYPASSRLS app role + the user's claim.

    Transaction-local (docs/multi-tenancy.md §2): both are discarded on the
    session's next commit/rollback, so every query that should be RLS-scoped
    must run inside the same transaction that applied them.
    """
    await db.execute(text(f"SET LOCAL ROLE {RLS_ROLE}"))
    await db.execute(
        text("SELECT set_config('request.jwt.claim.sub', :sub, true)"),
        {"sub": str(identity.user_id)},
    )


def build_authenticator(settings: Settings) -> Authenticator:
    """Select the authenticator for the configured auth mode."""
    if settings.auth_mode == "dev":
        return DevAuthenticator(
            secret=settings.dev_jwt_secret,
            leeway_seconds=settings.jwt_leeway_seconds,
        )
    return SupabaseAuthenticator(
        issuer=settings.supabase_issuer,
        jwt_secret=settings.supabase_jwt_secret,
        jwks_url=settings.supabase_jwks_url_resolved,
        leeway_seconds=settings.jwt_leeway_seconds,
    )


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AsyncIterator[Identity]:
    """Resolve the authenticated identity, or raise 401 (contracts/auth.md §1)."""
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials
    ):
        raise _unauthorized("missing bearer token")

    try:
        identity = build_authenticator(settings).authenticate(credentials.credentials)
    except AuthError as exc:
        raise _unauthorized(str(exc)) from exc

    # Identity → RLS propagation (transaction-local, resets on commit/rollback).
    await apply_identity_to_session(db, identity)

    # Bootstrap the profile row on first sight (docs/security.md §1).
    await ensure_profile(db, identity)

    yield identity


async def get_current_user_streaming(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> AsyncIterator[Identity]:
    """Streaming-route auth: resolve identity WITHOUT a request-scoped session.

    FastAPI keeps yield-dependency sessions open until the response body
    finishes, so for StreamingResponse routes a request session would pin the
    profiles UPSERT's row locks for the whole stream and block every
    concurrent request (docs/chat.md §4). This variant never opens a request
    session: the profile bootstrap (docs/security.md §1) runs on a short-lived
    session from the app's session factory and COMMITS immediately.
    """
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials
    ):
        raise _unauthorized("missing bearer token")

    try:
        identity = build_authenticator(settings).authenticate(credentials.credentials)
    except AuthError as exc:
        raise _unauthorized(str(exc)) from exc

    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as db:
        await apply_identity_to_session(db, identity)
        await ensure_profile(db, identity)
        await db.commit()

    yield identity
