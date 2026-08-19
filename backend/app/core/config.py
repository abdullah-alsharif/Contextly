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
    # Pre-deploy DDL role (docs/deployment.md §4); empty in dev → database_url.
    migration_database_url: str = ""
    # Log-level knob (docs/observability.md §1).
    log_level: str = "info"
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
    # Retrieval defaults (docs/rag.md §2, docs/security.md §4). Top-K and HNSW
    # search effort are operator-tunable (spec FR-005); the question length cap
    # matches the documented 4000-char limit (docs/security.md §4).
    retrieval_top_k: int = 6
    retrieval_ef_search: int = 40
    rag_query_max_chars: int = 4000
    # Embeddings (docs/rag.md §2, docs/ai-providers.md §2-4). The dimension MUST
    # match the pgvector column and the provider's model output (validated at
    # startup); keys are only needed for the nvidia/openrouter providers.
    embedding_dim: int = 1024
    embedding_batch_size: int = 32
    ai_embed_retries: int = 3
    ai_embed_retry_backoff_seconds: str = "1,2,4"
    nvidia_api_key: str = ""
    nvidia_embeddings_url: str = "https://integrate.api.nvidia.com/v1/embeddings"
    nvidia_chat_url: str = "https://integrate.api.nvidia.com/v1/chat/completions"
    nvidia_chat_model: str = "meta/llama-3.3-70b-instruct"
    openrouter_api_key: str = ""
    openrouter_embeddings_url: str = "https://openrouter.ai/api/v1/embeddings"
    openrouter_chat_url: str = "https://openrouter.ai/api/v1/chat/completions"
    openrouter_chat_model: str = "openai/gpt-4o-mini"
    # Chat (Phase 7; docs/chat.md §6, docs/security.md §4-5, research R15).
    # The question cap follows the documented 4000-char limit; the chat rate
    # limit is the documented in-process per-user bucket (30 req/min).
    chat_question_max_chars: int = 4000
    rate_limit_chat_per_minute: int = 30
    # Chat multi-turn context (Phase 13; docs/chat.md §4): rewrite budgets bound
    # the retrieval-query derivation input; context budgets bound the generation
    # window — both truncate oldest-first (advisory estimate_tokens caps).
    chat_rewrite_enabled: bool = True
    chat_rewrite_max_messages: int = 6  # ~3 turns
    chat_rewrite_max_tokens: int = 1500
    chat_context_max_messages: int = 12  # ~6 turns
    chat_context_max_tokens: int = 2000
    # General (non-chat) API traffic: distinct per-user bucket (docs/security.md
    # §5: "120 req/min general"; docs/deployment.md §3 `RATE_LIMIT_*` knobs).
    rate_limit_general_per_minute: int = 120
    # Download signed-URL TTL (docs/api.md §5 "5 min", docs/multi-tenancy.md §4).
    storage_signed_url_ttl_seconds: int = 300
    history_page_size: int = 50
    auto_rename_title_max_chars: int = 60

    @field_validator("auth_mode")
    @classmethod
    def _validate_auth_mode(cls, value: str) -> str:
        if value not in ("dev", "supabase"):
            raise ValueError(f"auth_mode must be 'dev' or 'supabase', got {value!r}")
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        # Accept stdlib level names in any case; unknown ones fail at startup.
        normalized = value.strip().lower()
        if normalized not in ("debug", "info", "warning", "error", "critical"):
            raise ValueError(
                f"log_level must be one of debug/info/warning/error/critical, "
                f"got {value!r}"
            )
        return normalized

    @field_validator("rate_limit_chat_per_minute", "rate_limit_general_per_minute")
    @classmethod
    def _validate_rate_limits(cls, value: int) -> int:
        # A non-positive budget would 429 every request — fail at startup.
        if value <= 0:
            raise ValueError(f"rate limit per minute must be > 0, got {value!r}")
        return value

    @field_validator("storage_signed_url_ttl_seconds")
    @classmethod
    def _validate_signed_url_ttl(cls, value: int) -> int:
        # Short-lived by design (docs/security.md §3 "signed URLs 5 min"). The
        # cap keeps `expires_at` truthful against the backend's token expiry
        # (Supabase clamps at 604800s).
        if value <= 0 or value > 3600:
            raise ValueError(
                "storage_signed_url_ttl_seconds must be in 1..3600 "
                f"(short expiry per docs/api.md §5), got {value!r}"
            )
        return value

    @field_validator("cors_origins")
    @classmethod
    def _split_origins(cls, value: str) -> str:
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
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
                    "or SUPABASE_URL/SUPABASE_JWKS_URL (RS256/ES256)"
                )

    @property
    def supabase_jwks_url_resolved(self) -> str:
        """JWKS endpoint for RS256/ES256 verification; empty when unavailable."""
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

    @property
    def ai_embed_retry_backoff_seconds_list(self) -> list[float]:
        return [
            float(seconds.strip())
            for seconds in self.ai_embed_retry_backoff_seconds.split(",")
            if seconds.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
