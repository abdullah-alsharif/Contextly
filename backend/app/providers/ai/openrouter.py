"""OpenRouterProvider: embeddings + chat via OpenRouter (OpenAI-compatible).

Contract: specs/006-document-embeddings/contracts/ai-provider.md §3, following
docs/ai-providers.md §2. Calls POST /api/v1/embeddings with the OpenAI
`dimensions` parameter so the returned vectors match the locked vector(1024)
column (research.md R2), and POST /api/v1/chat/completions for generation
(research R4/R15).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.providers.ai.base import estimate_tokens
from app.providers.ai.http import post_chat, post_embeddings

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1/embeddings"
DEFAULT_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/text-embedding-3-small"
DEFAULT_DIMS = 1024


class OpenRouterProvider:
    """OpenRouter embeddings + chat provider (docs/ai-providers.md §2)."""

    embedding_model = DEFAULT_MODEL
    embedding_dims = DEFAULT_DIMS
    embedding_max_input_tokens = 8191  # text-embedding-3-small cap
    supports_streaming = True

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        chat_url: str = DEFAULT_CHAT_URL,
        chat_model: str = "openai/gpt-4o-mini",
        retries: int = 3,
        backoff_seconds: tuple[float, ...] = (1.0, 2.0, 4.0),
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.chat_url = chat_url
        self.chat_model = chat_model
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self._transport = transport

    async def embed(
        self, texts: list[str], *, batch_size: int = 32, input_type: str = "passage"
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
                    max_input_tokens=self.embedding_max_input_tokens,
                    dimensions=self.embedding_dims,
                    retries=self.retries,
                    backoff_seconds=self.backoff_seconds,
                    transport=self._transport,
                )
            )
        return vectors

    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        """Complete a chat via OpenRouter (docs/ai-providers.md §2, research R4)."""
        return await post_chat(
            url=self.chat_url,
            api_key=self.api_key,
            model=self.chat_model,
            provider_name="openrouter",
            messages=messages,
            stream=stream,
            retries=self.retries,
            backoff_seconds=self.backoff_seconds,
            transport=self._transport,
        )

    async def count_tokens(self, text: str) -> int:
        """Advisory token estimate (shared heuristic, research R4)."""
        return estimate_tokens(text)
