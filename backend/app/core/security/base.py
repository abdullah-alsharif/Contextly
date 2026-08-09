"""Authenticator contract shared by dev and Supabase modes.

One thin module per constitution IV: replacing the vendor (or using dev mode)
must not require changes outside this package plus configuration.
"""
from __future__ import annotations

from typing import Protocol

from app.core.security.identity import Identity


class AuthError(Exception):
    """A token failed verification. Message is safe to return to clients."""


class Authenticator(Protocol):
    """Resolve a raw JWT into an Identity, or raise AuthError."""

    def authenticate(self, token: str) -> Identity:
        """Verify `token` and return its identity.

        Raises AuthError for any invalid token (bad signature, expired,
        malformed, wrong audience/issuer, non-UUID sub).
        """
        ...
