"""Shared `get_current_user` dependency guarding every /api/v1 business route.

Flow (contracts/auth.md §1, §4):
1. Parse `Authorization: Bearer <JWT>`.
2. Verify with the mode-selected authenticator (dev or Supabase).
3. Any failure → 401 (never 200).
4. On success, switch the request's DB session transaction-locally to the
   NOBYPASSRLS `contextly_app` role and set the user's claim, so every query
   in the request runs under RLS (docs/multi-tenancy.md §2) — the app never
   bypasses the database boundary.
5. Bootstrap the user's `profiles` row if missing (docs/security.md §1).
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security.base import AuthError, Authenticator
from app.core.security.dev import DevAuthenticator
from app.core.security.identity import Identity
from app.core.security.supabase import SupabaseAuthenticator
from app.db.session import get_db
from app.services.profiles import ensure_profile

_bearer = HTTPBearer(auto_error=False)

RLS_ROLE = "contextly_app"


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
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise _unauthorized("missing bearer token")

    try:
        identity = build_authenticator(settings).authenticate(credentials.credentials)
    except AuthError as exc:
        raise _unauthorized(str(exc)) from exc

    # Identity → RLS propagation (transaction-local, resets on commit/rollback).
    await db.execute(text(f"SET LOCAL ROLE {RLS_ROLE}"))
    await db.execute(
        text("SELECT set_config('request.jwt.claim.sub', :sub, true)"),
        {"sub": str(identity.user_id)},
    )

    # Bootstrap the profile row on first sight (docs/security.md §1).
    await ensure_profile(db, identity)

    yield identity
