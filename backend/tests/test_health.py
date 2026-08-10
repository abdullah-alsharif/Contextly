"""Contract tests for GET /healthz and GET / (contracts/healthz.md).

Health probes are dependency-injected so failure paths are deterministic.
"""
import os

import pytest
from fastapi.testclient import TestClient
from psycopg import connect as psycopg_connect

from app.core.config import Settings
from app.main import create_app, probe_ai_provider


def _healthy_app() -> TestClient:
    app = create_app(
        settings=Settings(database_url="postgresql://unused:unused@nowhere:1/unused"),
        health_checks={"database": lambda: True, "ai_provider": lambda: True},
    )
    return TestClient(app)


def _db_down_app() -> TestClient:
    app = create_app(
        settings=Settings(database_url="postgresql://unused:unused@nowhere:1/unused"),
        health_checks={"database": lambda: False, "ai_provider": lambda: True},
    )
    return TestClient(app)


def test_healthz_ok_shape() -> None:
    client = _healthy_app()
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "checks": {"database": True, "ai_provider": True}}
    assert response.headers["cache-control"] == "no-store"


def test_healthz_degraded_when_database_down() -> None:
    client = _db_down_app()
    response = client.get("/healthz")
    assert response.status_code == 503
    body = response.json()
    assert body == {
        "status": "degraded",
        "checks": {"database": False, "ai_provider": True},
    }


def test_healthz_probes_all_checks_even_when_one_fails() -> None:
    client = _db_down_app()
    body = client.get("/healthz").json()
    assert set(body["checks"]) == {"database", "ai_provider"}


def test_healthz_sets_cache_control_no_store() -> None:
    client = _healthy_app()
    assert client.get("/healthz").headers["cache-control"] == "no-store"


def test_x_request_id_header_present() -> None:
    client = _healthy_app()
    response = client.get("/healthz")
    request_id = response.headers.get("x-request-id")
    assert request_id and len(request_id) == 32


def test_hello_world() -> None:
    client = _healthy_app()
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "contextly-backend"


def _database_reachable() -> bool:
    url = os.getenv("DATABASE_URL")
    if not url:
        return False
    try:
        with psycopg_connect(url, connect_timeout=1) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _database_reachable(), reason="DATABASE_URL not reachable")
def test_healthz_real_database_probe() -> None:
    client = TestClient(create_app(settings=Settings()))
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["checks"]["database"] is True


def test_probe_ai_provider_reflects_configurability() -> None:
    # Provider construction is offline; health reflects "buildable with current config".
    assert probe_ai_provider(Settings(ai_provider="fake")) is True
    assert probe_ai_provider(Settings(ai_provider="nvidia")) is True
    assert probe_ai_provider(Settings(ai_provider="bogus")) is False
    assert probe_ai_provider(Settings(ai_provider="fake", app_env="production")) is False
