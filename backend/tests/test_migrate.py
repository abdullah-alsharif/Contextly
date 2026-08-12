"""Migration connection resolution (docs/deployment.md §4).

The pre-deploy migration step must use MIGRATION_DATABASE_URL — never the
runtime role — so resolution is a pure, testable decision.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.migrate import resolve_database_url


def test_resolve_falls_back_to_runtime_url_in_dev() -> None:
    settings = Settings(database_url="postgresql://runtime@db/app")
    assert resolve_database_url(settings) == "postgresql://runtime@db/app"


def test_resolve_prefers_migration_url_when_set() -> None:
    settings = Settings(
        database_url="postgresql://runtime@db/app",
        migration_database_url="postgresql://migrator@db/app",
    )
    assert resolve_database_url(settings) == "postgresql://migrator@db/app"


def test_migration_url_empty_by_default() -> None:
    assert Settings().migration_database_url == ""


def test_production_requires_migration_url() -> None:
    # Deploy blocker (docs/deployment.md §4): outside dev, refusing to run DDL
    # as the runtime role beats a silent fallback to DATABASE_URL.
    settings = Settings(
        database_url="postgresql://runtime@db/app", app_env="production"
    )
    with pytest.raises(RuntimeError, match="MIGRATION_DATABASE_URL"):
        resolve_database_url(settings)
    settings = Settings(
        database_url="postgresql://runtime@db/app",
        migration_database_url="postgresql://migrator@db/app",
        app_env="production",
    )
    assert resolve_database_url(settings) == "postgresql://migrator@db/app"
