"""Auth module: identity resolution for /api/v1 (contracts/auth.md).

Exports the pieces every other module needs: `Identity`, `get_current_user`,
and the `dev_token` helper for local tools/tests.
"""
from app.core.security.base import AuthError, Authenticator
from app.core.security.deps import get_current_user
from app.core.security.dev import DEV_AUDIENCE, DevAuthenticator, dev_token
from app.core.security.identity import Identity
from app.core.security.supabase import SUPABASE_AUDIENCE, SupabaseAuthenticator

__all__ = [
    "AuthError",
    "Authenticator",
    "DEV_AUDIENCE",
    "DevAuthenticator",
    "Identity",
    "SUPABASE_AUDIENCE",
    "SupabaseAuthenticator",
    "dev_token",
    "get_current_user",
]
