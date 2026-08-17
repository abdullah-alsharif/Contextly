"""AIProvider abstraction: protocol, errors, and embedding dimension guard.

Contract: specs/006-document-embeddings/contracts/ai-provider.md, following
docs/ai-providers.md §2/§4. Business code depends on this Protocol and nothing
else; vendors live behind build_ai_provider (constitution IV). The generation
surface (generate/count_tokens/chat_model) landed in Phase 7
(specs/008-chat-conversations, research R4).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from logging import getLogger
from typing import Any, Protocol

logger = getLogger(__name__)

# Chars/token floor for embedding input caps (docs/ai-providers.md §2): the 2.4
# prose ratio over-sizes code/math text (measured ~1.6 on dense pages).
EMBED_SAFE_CHARS_PER_TOKEN = 1.4


class AIProviderError(Exception):
    """AI backend failure (vendor error, network failure, bad response).

    Carries the provider name and, when a vendor responded, its HTTP status so
    callers can classify permanent vs transient failures (is_transient_status)
    and logs stay diagnosable (docs/ai-providers.md §2 contract notes).
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
    embedding_max_input_tokens: int  # vendor per-text input cap; pipeline clamps to it
    chat_model: str  # model used for generation (docs/ai-providers.md §2)
    supports_streaming: bool  # False → callers fall back to one full-answer event

    async def embed(
        self, texts: list[str], *, batch_size: int = 32, input_type: str = "passage"
    ) -> list[list[float]]:
        """Embed texts; order preserved. Raises AIProviderError on failure.

        `input_type` (query|passage) only matters for asymmetric models; others
        ignore it.
        """

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


def is_transient_status(status_code: int | None) -> bool:
    """True when a vendor status is worth retrying: 4xx (except 429) are
    deterministic rejections, 5xx/429/network (None) are transient."""
    return status_code is None or status_code >= 500 or status_code == 429


def embedding_cap_chars(max_input_tokens: int) -> int:
    """Char floor for a vendor's per-text token cap (EMBED_SAFE_CHARS_PER_TOKEN)."""
    return round(max_input_tokens * EMBED_SAFE_CHARS_PER_TOKEN)


def clamp_chunk_size_chars(chunk_size_chars: int, max_input_tokens: int) -> int:
    """Cap a chunk window so it cannot exceed the model's input cap."""
    return min(chunk_size_chars, embedding_cap_chars(max_input_tokens))


def truncate_to_embedding_cap(texts: list[str], max_input_tokens: int) -> list[str]:
    """Last-resort backstop for inputs outside the clamped chunking (e.g. long questions)."""
    cap_chars = embedding_cap_chars(max_input_tokens)
    truncated = [text[:cap_chars] for text in texts]
    cut = sum(len(text) > cap_chars for text in texts)
    if cut:
        logger.warning(
            "truncated %d/%d texts to embedding input cap | "
            "max_input_tokens=%d | cap_chars=%d",
            cut,
            len(texts),
            max_input_tokens,
            cap_chars,
        )
    return truncated


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
