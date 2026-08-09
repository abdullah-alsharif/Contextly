"""Dev-mode authenticator: JWT signed with a well-known dev secret.

Zero credentials: the secret has a documented dev default (env-overridable for
tests), and the same Bearer-JWT scheme as production is used so the
get_current_user path is identical in both modes (docs/local-dev.md §3,
constitution VI). The startup guard (config.validate_auth) makes this mode
impossible outside a dev environment.
"""
from __future__ import annotations

import time
import uuid

import jwt

from app.core.security.base import AuthError
from app.core.security.identity import Identity

DEV_AUDIENCE = "contextly-dev"


def dev_token(
    sub: uuid.UUID | str,
    secret: str = "contextly-dev-secret-0123456789abcdef",
    *,
    email: str | None = None,
    expires_in_seconds: int | None = 3600,
    issued_at: int | None = None,
    aud: str = DEV_AUDIENCE,
) -> str:
    """Mint a dev JWT (HS256) for local tools, tests, and the eval harness."""
    subject = str(sub)
    now = issued_at if issued_at is not None else int(time.time())
    payload: dict[str, object] = {"sub": subject, "aud": aud, "iat": now}
    if expires_in_seconds is not None:
        payload["exp"] = now + expires_in_seconds
    if email is not None:
        payload["email"] = email
    return jwt.encode(payload, secret, algorithm="HS256")


class DevAuthenticator:
    """Accept HS256 JWTs signed with the well-known dev secret."""

    def __init__(self, secret: str = "contextly-dev-secret-0123456789abcdef", leeway_seconds: int = 30) -> None:
        self._secret = secret
        self._leeway = leeway_seconds

    def authenticate(self, token: str) -> Identity:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                audience=DEV_AUDIENCE,
                leeway=self._leeway,
            )
        except jwt.PyJWTError as exc:
            raise AuthError(f"invalid dev token: {exc}") from exc
        return _identity_from_claims(claims)


def _identity_from_claims(claims: dict[str, object]) -> Identity:
    sub = claims.get("sub")
    if not isinstance(sub, str):
        raise AuthError("token sub is not a valid user id")
    try:
        user_id = uuid.UUID(sub)
    except (TypeError, ValueError, AttributeError) as exc:
        raise AuthError("token sub is not a valid user id") from exc
    email = claims.get("email")
    if not isinstance(email, str):
        email = None
    return Identity(user_id=user_id, email=email, claims=claims)
