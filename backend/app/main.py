"""FastAPI application: CORS, request-id middleware, hello-world + /healthz.

Business routes land under /api/v1 in later phases (docs/api.md); health is
infrastructure and stays at root (contracts/healthz.md, research.md D3). Auth
configuration is validated at startup (fails loudly on unsafe modes).
"""
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.api import api_router
from app.core.config import Settings, get_settings
from app.providers.ai import build_ai_provider
from app.providers.storage import build_storage_provider
from app.providers.storage.base import StorageProvider

logger = logging.getLogger(__name__)

SERVICE_NAME = "contextly-backend"
VERSION = "0.1.0"

HealthProbe = Callable[[], bool]


def probe_database(settings: Settings) -> bool:
    """True when a connection to DATABASE_URL succeeds (contracts/healthz.md)."""
    try:
        with psycopg.connect(settings.database_url, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def probe_ai_provider(settings: Settings) -> bool:
    """True when the configured provider can be built (fake is always healthy in dev)."""
    try:
        build_ai_provider(settings)
        return True
    except Exception:
        return False


def default_health_checks(settings: Settings) -> dict[str, HealthProbe]:
    return {
        "database": lambda: probe_database(settings),
        "ai_provider": lambda: probe_ai_provider(settings),
    }


def create_app(
    settings: Settings | None = None,
    health_checks: Mapping[str, HealthProbe] | None = None,
    storage_provider: StorageProvider | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_settings.validate_auth()
    build_ai_provider(resolved_settings)  # fail fast on bad AI config (contracts/ai-provider.md §4)
    checks = (
        dict(health_checks) if health_checks is not None else default_health_checks(resolved_settings)
    )

    app = FastAPI(
        title="Contextly Backend",
        version=VERSION,
        docs_url=None,
        redoc_url=None,
    )
    app.state.storage_provider = storage_provider or build_storage_provider(resolved_settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )

    @app.middleware("http")
    async def add_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

    @app.get("/")
    def hello_world() -> dict[str, str]:
        return {"service": SERVICE_NAME, "version": VERSION}

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        check_results = {name: bool(probe()) for name, probe in checks.items()}
        all_ok = all(check_results.values())
        body = {"status": "ok" if all_ok else "degraded", "checks": check_results}
        return JSONResponse(
            content=body,
            status_code=200 if all_ok else 503,
            headers={"Cache-Control": "no-store"},
        )

    app.include_router(api_router)
    return app


app = create_app()
