from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend configuration, populated from environment (dev-safe defaults)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(
        default="postgresql://contextly:contextly@db:5432/contextly"
    )
    ai_provider: str = "fake"
    storage_provider: str = "local"
    local_storage_dir: str = "/data/storage"
    auth_mode: str = "dev"
    cors_origins: str = "http://localhost:3000"
    # Directory of numbered SQL migration files, relative to the workdir.
    migrations_dir: str = "infrastructure/migrations"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()