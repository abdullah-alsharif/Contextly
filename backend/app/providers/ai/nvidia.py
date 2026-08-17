"""NvidiaProvider: NVIDIA NIM Build embeddings + chat.

Contract: specs/006-document-embeddings/contracts/ai-provider.md §3, following
docs/ai-providers.md §2. Calls the OpenAI-compatible POST /v1/embeddings and
/v1/chat/completions endpoints via the shared helpers; chat model + URL come
from settings (research R4/R15).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from typing import Any

import httpx

from app.providers.ai.base import estimate_tokens
from app.providers.ai.http import post_chat, post_embeddings

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1/embeddings"
DEFAULT_CHAT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
# Free NV-API routes nv-embedqa-e5-v5 (1024 dims); bge-m3 retired there (404).
# Asymmetric: requires `input_type`, set by the retrieval service.
DEFAULT_MODEL = "nvidia/nv-embedqa-e5-v5"
DEFAULT_DIMS = 1024
# nemotron chat models are not routed by the free NV-API (404) — llama-3.3 is.
DEFAULT_CHAT_MODEL = "meta/llama-3.3-70b-instruct"


class NvidiaProvider:
    """NVIDIA NIM Build embeddings + chat provider (docs/ai-providers.md §2)."""

    embedding_model = DEFAULT_MODEL
    embedding_dims = DEFAULT_DIMS
    embedding_max_input_tokens = 512  # nv-embedqa-e5-v5 hard cap
    supports_streaming = True

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        chat_url: str = DEFAULT_CHAT_URL,
        chat_model: str = DEFAULT_CHAT_MODEL,
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
        """Embed texts in batches; order preserved (contracts §1).

        `input_type` is required by nv-embedqa-e5-v5 (query|passage); symmetric
        providers ignore it.
        """
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
                    provider_name="nvidia",
                    texts=batch,
                    embedding_dims=self.embedding_dims,
                    max_input_tokens=self.embedding_max_input_tokens,
                    extra_body={"input_type": input_type},
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
        """Complete a chat via NIM Build (docs/ai-providers.md §2, research R4)."""
        return await post_chat(
            url=self.chat_url,
            api_key=self.api_key,
            model=self.chat_model,
            provider_name="nvidia",
            messages=messages,
            stream=stream,
            retries=self.retries,
            backoff_seconds=self.backoff_seconds,
            transport=self._transport,
        )

    async def count_tokens(self, text: str) -> int:
        """Advisory token estimate (shared heuristic, research R4)."""
        return estimate_tokens(text)
