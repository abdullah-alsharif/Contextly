"""AIProvider abstraction: protocol, errors, and embedding dimension guard.

Contract: specs/006-document-embeddings/contracts/ai-provider.md, following
docs/ai-providers.md §2/§4. Business code depends on this Protocol and nothing
else; vendors live behind build_ai_provider (constitution IV). The generation
surface (generate/count_tokens/chat_model) landed in Phase 7
(specs/008-chat-conversations, research R4).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol


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
    """Text-embedding + chat interface shared by the fake/NVIDIA/OpenRouter providers."""

    embedding_dims: int  # must match the pgvector column dim (validated at startup)
    embedding_model: str  # for logs/metrics
    chat_model: str  # model used for generation (docs/ai-providers.md §2)
    supports_streaming: bool  # False → callers fall back to one full-answer event

    async def embed(
        self, texts: list[str], *, batch_size: int = 32
    ) -> list[list[float]]:
        """Embed texts; order preserved. Raises AIProviderError on failure."""

    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        """Complete a chat; returns str when stream=False, token iterator when True.

        messages follow the OpenAI shape: [{"role": "system"|"user"|"assistant",
        "content": str}]. Streaming yields incremental text deltas. Raises
        AIProviderError on failure (pre-body HTTP errors, malformed streams).
        """

    async def count_tokens(self, text: str) -> int:
        """Advisory token estimate for metrics (docs/api.md §4)."""


def estimate_tokens(text: str) -> int:
    """Shared heuristic: ~4 chars per token (research R4).

    Token counts on messages are advisory metrics, not billing inputs, so one
    provider-independent approximation is sufficient for every provider.
    """
    return max(1, len(text) // 4)


def validate_dimension(
    provider: AIProvider, expected_dims: int, provider_name: str
) -> None:
    """Shared startup guard: provider dims must equal the pgvector column dim."""
    if provider.embedding_dims != expected_dims:
        raise RuntimeError(
            f"AI provider {provider_name!r} reports embedding_dims="
            f"{provider.embedding_dims}, but the database column is vector("
            f"{expected_dims}) — embedding dimension must equal the model output "
            f"(docs/rag.md §2, docs/database.md §3)"
        )
