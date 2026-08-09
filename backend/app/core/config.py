from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend configuration, populated from environment (dev-safe defaults).

    Auth contract: specs/003-jwt-authentication/contracts/auth.md §7.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(
        default="postgresql://contextly:contextly@db:5432/contextly"
    )
    ai_provider: str = "fake"
    storage_provider: str = "local"
    local_storage_dir: str = "/data/storage"
    storage_bucket: str = "documents"
    upload_max_bytes: int = 10 * 1024 * 1024
    auth_mode: str = "dev"
    app_env: str = "dev"
    dev_jwt_secret: str = "contextly-dev-secret-0123456789abcdef"
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_jwks_url: str = ""
    jwt_leeway_seconds: int = 30
    cors_origins: str = "http://localhost:3000"
    # Directory of numbered SQL migration files, relative to the workdir.
    migrations_dir: str = "infrastructure/migrations"
    # Worker loop (docs/ingestion.md §3): poll interval, claim lease, retry policy.
    worker_poll_interval_seconds: int = 5
    worker_lease_seconds: int = 300
    worker_max_retries: int = 3
    worker_retry_backoff_seconds: str = "1,5,30"
    # Chunking defaults (docs/ingestion.md §4.3, docs/rag.md §3).
    chunk_size_tokens: int = 500
    chunk_overlap_tokens: int = 50

    @field_validator("auth_mode")
    @classmethod
    def _validate_auth_mode(cls, value: str) -> str:
        if value not in ("dev", "supabase"):
            raise ValueError(f"auth_mode must be 'dev' or 'supabase', got {value!r}")
        return value

    @field_validator("cors_origins")
    @classmethod
    def _split_origins(cls, value: str) -> str:
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    def validate_auth(self) -> None:
        """Fail loudly on unsafe auth configuration (contracts/auth.md §2-3).

        - dev mode is only ever allowed in a dev environment.
        - supabase mode requires something to verify against.
        Called at app startup; a misconfiguration aborts the process.
        """
        if self.auth_mode == "dev" and self.app_env != "dev":
            raise RuntimeError(
                "AUTH_MODE=dev is only allowed when APP_ENV=dev "
                f"(got APP_ENV={self.app_env!r})"
            )
        if self.auth_mode == "supabase":
            jwks = self.supabase_jwks_url or (
                f"{self.supabase_url}/auth/v1/.well-known/jwks.json"
                if self.supabase_url
                else ""
            )
            if not self.supabase_jwt_secret and not jwks:
                raise RuntimeError(
                    "AUTH_MODE=supabase requires SUPABASE_JWT_SECRET (HS256) "
                    "or SUPABASE_URL/SUPABASE_JWKS_URL (RS256)"
                )

    @property
    def supabase_jwks_url_resolved(self) -> str:
        """JWKS endpoint for RS256 verification; empty when unavailable."""
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        if self.supabase_url:
            return f"{self.supabase_url}/auth/v1/.well-known/jwks.json"
        return ""

    @property
    def supabase_issuer(self) -> str:
        """Expected `iss` claim for Supabase-issued tokens."""
        return f"{self.supabase_url}/auth/v1"

    @property
    def worker_retry_backoff_seconds_list(self) -> list[int]:
        return [
            int(seconds.strip())
            for seconds in self.worker_retry_backoff_seconds.split(",")
            if seconds.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()