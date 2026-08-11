"""Deployment guard rails proven at startup/config (docs/security.md §1, §3).

No database required. The `AUTH_MODE=dev` guard already has settings-level
coverage (test_auth_unit.py); this adds the app-level proof (create_app must
refuse to boot). The signed-URL TTL validator guarantees a misconfiguration can
never mint non-expiring URLs. Frontend transport header checks are a Node-side
test in `frontend/scripts/check-security-headers.mjs` (spec SC-005).
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.main import create_app


def test_create_app_refuses_dev_auth_outside_dev_env() -> None:
    settings = Settings(auth_mode="dev", app_env="production")
    # validate_auth runs first in create_app (before any provider/DB work).
    with pytest.raises(RuntimeError, match="only allowed when APP_ENV=dev"):
        create_app(settings=settings)


def test_dev_auth_ok_in_dev_env() -> None:
    settings = Settings(auth_mode="dev", app_env="dev")
    app = create_app(settings=settings)
    assert app.state.general_rate_limiter.per_minute == settings.rate_limit_general_per_minute


def test_signed_url_ttl_must_be_short_and_positive() -> None:
    # A signed URL must always expire within a short, truthful window
    # (docs/security.md §3, docs/api.md §5): reject non-positive and any value
    # that could outlive the storage backend's token clamp.
    for bad in (0, -30):
        with pytest.raises(ValueError, match="storage_signed_url_ttl_seconds"):
            Settings(storage_signed_url_ttl_seconds=bad)
    with pytest.raises(ValueError, match="storage_signed_url_ttl_seconds"):
        Settings(storage_signed_url_ttl_seconds=1_000_000)


def test_rate_limits_must_be_positive() -> None:
    # A zero budget would 429 every request — fail at startup, not silently.
    for field in ("rate_limit_chat_per_minute", "rate_limit_general_per_minute"):
        with pytest.raises(ValueError, match="rate limit per minute"):
            Settings(**{field: 0})
        with pytest.raises(ValueError, match="rate limit per minute"):
            Settings(**{field: -5})


def test_general_rate_limit_defaults_match_docs() -> None:
    # docs/security.md §5: 120 general / 30 chat.
    settings = Settings()
    assert settings.rate_limit_general_per_minute == 120
    assert settings.rate_limit_chat_per_minute == 30
    assert settings.storage_signed_url_ttl_seconds == 300