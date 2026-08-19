"""Supabase-issued JWT verification (HS256 shared secret and/or JWKS).

Validates signature + expiry + issuer + audience per docs/security.md §1.
RS256/ES256 keys come from the project JWKS endpoint via PyJWKClient, which
caches the key set (default lifespan 300s) — no per-request network calls. For
offline tests an injected key resolver is used instead (docs/testing.md §1).

Supabase projects issue tokens in a mix of algorithms: legacy HS256 shared
secret, RS256, and — for newer projects — ES256 via the JWKS endpoint (key
migration state, research.md §2); the resolver inspects the token header and
picks the right key: HS256 → shared secret, RS256/ES256 → JWKS by `kid`.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable

import jwt

from app.core.security.base import AuthError
from app.core.security.dev import _identity_from_claims
from app.core.security.identity import Identity

SUPABASE_AUDIENCE = "authenticated"


def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=300)


class _KeyResolver:
    """Pick the verification key from the token header (HS256 vs RS256/ES256)."""

    def __init__(
        self,
        jwt_secret: str = "",
        jwks_url: str = "",
        jwks_client: jwt.PyJWKClient | None = None,
    ) -> None:
        self._secret = jwt_secret
        self._client = jwks_client or (_jwks_client(jwks_url) if jwks_url else None)

    def __call__(self, token: str) -> str | jwt.PyJWK:
        alg = self._header_alg(token)
        if alg == "HS256":
            if not self._secret:
                raise AuthError("HS256 token but no SUPABASE_JWT_SECRET configured")
            return self._secret
        if alg in ("RS256", "ES256"):
            if self._client is None:
                raise AuthError("RS256/ES256 token but no JWKS endpoint configured")
            return self._client.get_signing_key_from_jwt(token)
        raise AuthError(f"unsupported token algorithm: {alg!r}")

    @staticmethod
    def _header_alg(token: str) -> str:
        try:
            header = token.split(".", 1)[0]
            padded = header + "=" * (-len(header) % 4)
            return str(json.loads(base64.urlsafe_b64decode(padded)).get("alg", ""))
        except Exception as exc:
            raise AuthError("malformed token header") from exc


class SupabaseAuthenticator:
    """Verify Supabase-issued access tokens (contracts/auth.md §2).

    Requires a `jwt_secret` (HS256), a `jwks_url` (RS256), or both. `issuer`
    must be the Supabase auth base URL (docs/security.md §1: issuer + audience
    validated on every request).
    """

    def __init__(
        self,
        *,
        issuer: str,
        jwt_secret: str = "",
        jwks_url: str = "",
        leeway_seconds: int = 30,
        key_resolver: Callable[[str], str | bytes | jwt.PyJWK] | None = None,
    ) -> None:
        if not issuer:
            raise AuthError("SupabaseAuthenticator requires an issuer (SUPABASE_URL)")
        if not jwt_secret and not jwks_url and not key_resolver:
            raise AuthError("SupabaseAuthenticator requires a secret or JWKS URL")
        self._issuer = issuer
        self._leeway = leeway_seconds
        self._resolve_key = key_resolver or _KeyResolver(jwt_secret, jwks_url)

    def authenticate(self, token: str) -> Identity:
        try:
            key = self._resolve_key(token)
            claims = jwt.decode(
                token,
                key,
                algorithms=["HS256", "RS256", "ES256"],
                audience=SUPABASE_AUDIENCE,
                issuer=self._issuer,
                leeway=self._leeway,
            )
        except jwt.PyJWTError as exc:
            raise AuthError(f"invalid token: {exc}") from exc
        except AuthError:
            raise
        return _identity_from_claims(claims)
