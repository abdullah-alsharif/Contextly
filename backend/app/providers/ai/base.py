"""AIProvider abstraction: protocol, errors, and embedding dimension guard.

Contract: specs/006-document-embeddings/contracts/ai-provider.md, following
docs/ai-providers.md §2/§4. Business code depends on this Protocol and nothing
else; vendors live behind build_ai_provider (constitution IV). Only the
embedding surface is implemented this phase — generate/count_tokens are Phase 7.
"""
from __future__ import annotations

from typing import Protocol


class AIProviderError(Exception):
    """AI backend failure (vendor error, network failure, bad response).

    Carries the provider name and, when a vendor responded, its HTTP status so
    callers can classify permanent (401/403) vs transient failures and logs
    stay diagnosable (docs/ai-providers.md §2 contract notes).
    """

    def __init__(self, message: str, *, provider: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.status_code = status_code


class AIProvider(Protocol):
    """Text-embedding interface shared by the fake/NVIDIA/OpenRouter providers."""

    embedding_dims: int  # must match the pgvector column dim (validated at startup)
    embedding_model: str  # for logs/metrics

    async def embed(
        self, texts: list[str], *, batch_size: int = 32
    ) -> list[list[float]]:
        """Embed texts; order preserved. Raises AIProviderError on failure."""


def validate_dimension(provider: AIProvider, expected_dims: int, provider_name: str) -> None:
    """Shared startup guard: provider dims must equal the pgvector column dim."""
    if provider.embedding_dims != expected_dims:
        raise RuntimeError(
            f"AI provider {provider_name!r} reports embedding_dims="
            f"{provider.embedding_dims}, but the database column is vector("
            f"{expected_dims}) — embedding dimension must equal the model output "
            f"(docs/rag.md §2, docs/database.md §3)"
        )
