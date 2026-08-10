"""OpenRouterProvider: embeddings via OpenRouter (OpenAI-compatible).

Contract: specs/006-document-embeddings/contracts/ai-provider.md §3, following
docs/ai-providers.md §2. Calls POST /api/v1/embeddings with the OpenAI
`dimensions` parameter so the returned vectors match the locked vector(1024)
column (research.md R2); `generate`/`count_tokens` are Phase 7 (spec FR-012).
"""
from __future__ import annotations

import httpx

from app.providers.ai.http import post_embeddings

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1/embeddings"
DEFAULT_MODEL = "openai/text-embedding-3-small"
DEFAULT_DIMS = 1024


class OpenRouterProvider:
    """OpenRouter embeddings provider (docs/ai-providers.md §2)."""

    embedding_model = DEFAULT_MODEL
    embedding_dims = DEFAULT_DIMS

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        retries: int = 3,
        backoff_seconds: tuple[float, ...] = (1.0, 2.0, 4.0),
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self._transport = transport

    async def embed(
        self, texts: list[str], *, batch_size: int = 32
    ) -> list[list[float]]:
        """Embed texts in batches; order preserved (contracts §1)."""
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            vectors.extend(
                await post_embeddings(
                    url=self.base_url,
                    api_key=self.api_key,
                    model=self.embedding_model,
                    provider_name="openrouter",
                    texts=batch,
                    embedding_dims=self.embedding_dims,
                    dimensions=self.embedding_dims,
                    retries=self.retries,
                    backoff_seconds=self.backoff_seconds,
                    transport=self._transport,
                )
            )
        return vectors
