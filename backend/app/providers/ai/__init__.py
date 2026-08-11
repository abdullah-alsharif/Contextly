"""AIProvider factory: env-switched provider selection (constitution IV).

AI_PROVIDER=fake → FakeProvider (zero credentials, dev/tests, offline);
AI_PROVIDER=nvidia → NvidiaProvider (NIM Build, nvidia/bge-m3);
AI_PROVIDER=openrouter → OpenRouterProvider. Unknown values fail loudly at
startup (contracts/ai-provider.md §3, mirrors build_storage_provider).

Startup validation (contracts/ai-provider.md §4, research.md R4):
- the provider's embedding_dims MUST equal settings.embedding_dim;
- AI_PROVIDER=fake is only ever allowed in a dev environment (mirrors the
  AUTH_MODE=dev guard in config.py::validate_auth).
"""

from __future__ import annotations

from app.core.config import Settings
from app.providers.ai.base import AIProvider, validate_dimension
from app.providers.ai.fake import FakeProvider
from app.providers.ai.nvidia import NvidiaProvider
from app.providers.ai.openrouter import OpenRouterProvider


def build_ai_provider(settings: Settings) -> AIProvider:
    """Return the AI provider selected by settings.ai_provider, validated.

    Raises ValueError for unknown providers, RuntimeError for invalid
    dimension/fake-in-prod configurations. Called at startup by both the API
    (create_app) and the worker so misconfiguration aborts the process.
    """
    backoff = tuple(settings.ai_embed_retry_backoff_seconds_list)
    provider: AIProvider
    if settings.ai_provider == "fake":
        if settings.app_env != "dev":
            raise RuntimeError(
                "AI_PROVIDER=fake is only allowed when APP_ENV=dev "
                f"(got APP_ENV={settings.app_env!r})"
            )
        provider = FakeProvider(embedding_dims=settings.embedding_dim)
    elif settings.ai_provider == "nvidia":
        provider = NvidiaProvider(
            api_key=settings.nvidia_api_key,
            base_url=settings.nvidia_embeddings_url,
            chat_url=settings.nvidia_chat_url,
            chat_model=settings.nvidia_chat_model,
            retries=settings.ai_embed_retries,
            backoff_seconds=backoff,
        )
    elif settings.ai_provider == "openrouter":
        provider = OpenRouterProvider(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_embeddings_url,
            chat_url=settings.openrouter_chat_url,
            chat_model=settings.openrouter_chat_model,
            retries=settings.ai_embed_retries,
            backoff_seconds=backoff,
        )
    else:
        raise ValueError(
            "ai_provider must be 'fake', 'nvidia', or 'openrouter', "
            f"got {settings.ai_provider!r}"
        )
    validate_dimension(provider, settings.embedding_dim, settings.ai_provider)
    return provider
