"""Offline auth unit tests: token matrix + startup guards (docs/testing.md §1).

No database and no network: RS256 is exercised with a locally generated RSA
keypair + injected PyJWKSet (contracts/auth.md §2 allows an injected resolver).
Matrix: absent/malformed/expired/wrong-signature/wrong-audience/wrong-issuer/
valid dev/valid prod HS256/valid prod RS256.
"""
from __future__ import annotations

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import Settings
from app.core.security.base import AuthError
from app.core.security.dev import DEV_AUDIENCE, DevAuthenticator, dev_token
from app.core.security.supabase import (
    SUPABASE_AUDIENCE,
    SupabaseAuthenticator,
)

DEV_SECRET = "contextly-dev-secret-0123456789abcdef"
SUB_A = uuid.UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")


# --- Dev authenticator ---------------------------------------------------


def test_dev_token_roundtrip() -> None:
    token = dev_token(SUB_A, secret=DEV_SECRET, email="a@dev.contextly.local")
    identity = DevAuthenticator(secret=DEV_SECRET).authenticate(token)
    assert identity.user_id == SUB_A
    assert identity.email == "a@dev.contextly.local"


def test_dev_expired_token_rejected() -> None:
    token = dev_token(SUB_A, secret=DEV_SECRET, expires_in_seconds=-3600)
    with pytest.raises(AuthError):
        DevAuthenticator(secret=DEV_SECRET).authenticate(token)


def test_dev_wrong_secret_rejected() -> None:
    token = dev_token(SUB_A, secret="someone-elses-secret-0123456789abcdef")
    with pytest.raises(AuthError):
        DevAuthenticator(secret=DEV_SECRET).authenticate(token)


def test_dev_malformed_token_rejected() -> None:
    with pytest.raises(AuthError):
        DevAuthenticator(secret=DEV_SECRET).authenticate("not.a.jwt")


def test_dev_non_uuid_sub_rejected() -> None:
    token = jwt.encode(
        {"sub": "not-a-uuid", "aud": DEV_AUDIENCE, "exp": int(time.time()) + 3600},
        DEV_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(AuthError):
        DevAuthenticator(secret=DEV_SECRET).authenticate(token)


# --- Supabase authenticator (HS256) ---------------------------------------


def _supabase_hs256() -> SupabaseAuthenticator:
    return SupabaseAuthenticator(
        issuer="https://xyz.supabase.co/auth/v1",
        jwt_secret="supabase-secret-0123456789abcdef",
    )


def _supabase_hs256_token(
    *,
    sub: uuid.UUID = SUB_A,
    aud: str = SUPABASE_AUDIENCE,
    iss: str = "https://xyz.supabase.co/auth/v1",
    expires_in_seconds: int = 3600,
    secret: str = "supabase-secret-0123456789abcdef",
) -> str:
    return jwt.encode(
        {
            "sub": str(sub),
            "aud": aud,
            "iss": iss,
            "iat": int(time.time()),
            "exp": int(time.time()) + expires_in_seconds,
        },
        secret,
        algorithm="HS256",
    )


def test_supabase_hs256_valid() -> None:
    identity = _supabase_hs256().authenticate(_supabase_hs256_token())
    assert identity.user_id == SUB_A


def test_supabase_hs256_expired_rejected() -> None:
    with pytest.raises(AuthError):
        _supabase_hs256().authenticate(
            _supabase_hs256_token(expires_in_seconds=-3600)
        )


def test_supabase_hs256_wrong_signature_rejected() -> None:
    with pytest.raises(AuthError):
        _supabase_hs256().authenticate(
            _supabase_hs256_token(secret="some-other-secret-0123456789abcdef")
        )


def test_supabase_hs256_wrong_audience_rejected() -> None:
    with pytest.raises(AuthError):
        _supabase_hs256().authenticate(_supabase_hs256_token(aud="service_role"))


def test_supabase_hs256_wrong_issuer_rejected() -> None:
    with pytest.raises(AuthError):
        _supabase_hs256().authenticate(
            _supabase_hs256_token(iss="https://evil.example.com/auth/v1")
        )


def test_supabase_alg_pinned_against_none() -> None:
    token = jwt.encode(
        {
            "sub": str(SUB_A),
            "aud": SUPABASE_AUDIENCE,
            "iss": "https://xyz.supabase.co/auth/v1",
            "exp": int(time.time()) + 3600,
        },
        None,
        algorithm="none",
    )
    with pytest.raises(AuthError):
        _supabase_hs256().authenticate(token)


def test_supabase_missing_config_rejected() -> None:
    with pytest.raises(AuthError):
        SupabaseAuthenticator(issuer="https://x.supabase.co/auth/v1")


def test_supabase_requires_issuer() -> None:
    with pytest.raises(AuthError):
        SupabaseAuthenticator(issuer="", jwt_secret="s")


# --- Supabase authenticator (RS256 via injected local JWKS) ----------------


@pytest.fixture(scope="module")
def rsa_pem() -> tuple[str, str]:
    """Local RSA keypair as (private PEM, public PEM); no network."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode(),
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode(),
    )


def _rs256_token(private_pem: str, *, expires_in_seconds: int = 3600) -> str:
    return jwt.encode(
        {
            "sub": str(SUB_A),
            "aud": SUPABASE_AUDIENCE,
            "iss": "https://xyz.supabase.co/auth/v1",
            "iat": int(time.time()),
            "exp": int(time.time()) + expires_in_seconds,
        },
        private_pem,
        algorithm="RS256",
    )


def test_supabase_rs256_valid(rsa_pem: tuple[str, str]) -> None:
    private_pem, public_pem = rsa_pem
    auth = SupabaseAuthenticator(
        issuer="https://xyz.supabase.co/auth/v1",
        key_resolver=lambda token: public_pem,
    )
    assert auth.authenticate(_rs256_token(private_pem)).user_id == SUB_A


def test_supabase_rs256_expired_rejected(rsa_pem: tuple[str, str]) -> None:
    private_pem, public_pem = rsa_pem
    auth = SupabaseAuthenticator(
        issuer="https://xyz.supabase.co/auth/v1",
        key_resolver=lambda token: public_pem,
    )
    with pytest.raises(AuthError):
        auth.authenticate(_rs256_token(private_pem, expires_in_seconds=-3600))


def test_supabase_rs256_wrong_signature_rejected(rsa_pem: tuple[str, str]) -> None:
    _private_pem, public_pem = rsa_pem
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    auth = SupabaseAuthenticator(
        issuer="https://xyz.supabase.co/auth/v1",
        key_resolver=lambda token: public_pem,
    )
    with pytest.raises(AuthError):
        auth.authenticate(_rs256_token(other_pem))


# --- get_current_user dependency (no DB) -----------------------------------

def _run(agen):
    """Exhaust an async generator to its yielded value (no pytest-asyncio)."""

    import asyncio

    async def collect():
        result = None
        async for item in agen:
            result = item
        return result

    return asyncio.run(collect())


def test_get_current_user_missing_header_401() -> None:
    from app.core.security.deps import get_current_user

    with pytest.raises(Exception) as exc_info:
        _run(get_current_user(credentials=None, db=object(), settings=Settings()))
    assert exc_info.value.status_code == 401


def test_get_current_user_bad_scheme_401() -> None:
    from fastapi.security import HTTPAuthorizationCredentials

    from app.core.security.deps import get_current_user

    with pytest.raises(Exception) as exc_info:
        _run(
            get_current_user(
                credentials=HTTPAuthorizationCredentials(scheme="Basic", credentials="x"),
                db=object(),
                settings=Settings(),
            )
        )
    assert exc_info.value.status_code == 401


def test_get_current_user_emits_rls_statements() -> None:
    """Valid dev token → Identity + RLS setup statements on the session."""

    class FakeResult:
        def scalar_one(self) -> int:
            return 1  # pretend the auth shim exists (single-column auth.users)

    class FakeSession:
        def __init__(self) -> None:
            self.statements: list[str] = []
            self.params: list[dict] = []

        async def execute(self, statement: object, params: dict | None = None) -> FakeResult:
            self.statements.append(str(statement))
            self.params.append(params or {})
            return FakeResult()

    from fastapi.security import HTTPAuthorizationCredentials

    from app.core.security.deps import get_current_user

    session = FakeSession()
    token = dev_token(SUB_A, secret=DEV_SECRET)
    identity = _run(
        get_current_user(
            credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
            db=session,
            settings=Settings(),
        )
    )

    assert identity is not None and identity.user_id == SUB_A
    assert any("SET LOCAL ROLE" in s and "contextly_app" in s for s in session.statements)
    assert session.params and session.params[1]["sub"] == str(SUB_A)


def test_get_current_user_invalid_token_401_before_db() -> None:
    """Invalid tokens never reach the DB (no role/claim statements emitted)."""

    class FakeSession:
        def __init__(self) -> None:
            self.statements: list[str] = []

        async def execute(self, statement: object, params: dict | None = None) -> None:
            self.statements.append(str(statement))

    from fastapi.security import HTTPAuthorizationCredentials

    from app.core.security.deps import get_current_user

    session = FakeSession()
    with pytest.raises(Exception) as exc_info:
        _run(
            get_current_user(
                credentials=HTTPAuthorizationCredentials(
                    scheme="Bearer", credentials="garbage.token.value"
                ),
                db=session,
                settings=Settings(),
            )
        )
    assert exc_info.value.status_code == 401
    assert session.statements == []


# --- Startup guards (spec FR-008, contracts/auth.md §2-3) -------------------


def test_settings_validate_auth_dev_mode_requires_dev_env() -> None:
    settings = Settings(auth_mode="dev", app_env="production")
    with pytest.raises(RuntimeError, match="only allowed when APP_ENV=dev"):
        settings.validate_auth()


def test_settings_validate_auth_supabase_requires_secret_or_jwks() -> None:
    settings = Settings(auth_mode="supabase", supabase_url="", supabase_jwt_secret="")
    with pytest.raises(RuntimeError, match="SUPABASE_JWT_SECRET"):
        settings.validate_auth()


def test_settings_validate_auth_supabase_with_secret_ok() -> None:
    settings = Settings(
        auth_mode="supabase",
        supabase_url="https://xyz.supabase.co",
        supabase_jwt_secret="s",
    )
    settings.validate_auth()  # no raise


def test_settings_validate_auth_dev_dev_env_ok() -> None:
    settings = Settings(auth_mode="dev", app_env="dev")
    settings.validate_auth()  # no raise


def test_settings_auth_mode_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        Settings(auth_mode="magic")
