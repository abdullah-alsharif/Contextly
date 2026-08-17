"""FakeProvider: deterministic, zero-credential, offline embeddings + chat.

Contract: specs/006-document-embeddings/contracts/ai-provider.md §3, following
docs/ai-providers.md §2 ("FakeProvider (deterministic embeddings + canned
answers) exists for tests and offline development — no API key, no cost, no
flakiness in CI"). Purely stdlib: SHA-256 of the text seeds a `random.Random`,
so the same text always yields the same vector and no dependencies are added
(research.md R6). Dev/CI only — the factory refuses to build it outside a dev
environment (contracts/ai-provider.md §4).

The chat surface (Phase 7, research R4) streams a deterministic canned answer
built from the question — word-level deltas so SSE tests can assert
accumulation — and estimates tokens with the shared heuristic.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import AsyncIterator
from typing import Any

from app.providers.ai.base import AIProviderError, estimate_tokens

_CANNED_SUFFIX = (
    "Based on your documents, the answer is clear and can be cited from the "
    "retrieved excerpts."
)


class FakeProvider:
    """Deterministic embedding + chat provider for dev and tests (offline, no keys)."""

    embedding_model = "fake-embedding"
    chat_model = "fake-chat"
    supports_streaming = True
    embedding_max_input_tokens = 8192  # no vendor cap; must not shrink tuned windows

    def __init__(self, embedding_dims: int = 1024):
        self.embedding_dims = embedding_dims

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        rng = random.Random(digest)
        return [rng.uniform(-1.0, 1.0) for _ in range(self.embedding_dims)]

    async def embed(
        self, texts: list[str], *, batch_size: int = 32, input_type: str = "passage"
    ) -> list[list[float]]:
        """Embed texts deterministically; order preserved (no-op on empty input)."""
        if not texts:
            return []
        try:
            return [self._vector(text) for text in texts]
        except Exception as exc:  # noqa: BLE001 - provider boundary: never leak
            raise AIProviderError(
                f"fake embedding failed: {exc}", provider="fake"
            ) from exc

    def _answer(self, messages: list[dict[str, Any]]) -> str:
        """Deterministic canned answer: echoed question + fixed suffix."""
        user_parts = [
            message["content"] for message in messages if message.get("role") == "user"
        ]
        question = user_parts[-1].strip() if user_parts else ""
        # Echo the question itself, not chat.py's <user_question> delimiters.
        if question.startswith("<user_question>") and question.endswith(
            "</user_question>"
        ):
            question = question[len("<user_question>") : -len("</user_question>")]
        return f'Answer for "{question}": {_CANNED_SUFFIX}'

    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        """Complete a chat with a deterministic canned answer (research R4).

        Streaming yields word-level deltas of the same final text so callers
        can accumulate them back into the full answer. Raises AIProviderError
        on any unexpected failure (never leaks internal exceptions).
        """
        try:
            answer = self._answer(messages)
        except Exception as exc:  # noqa: BLE001 - provider boundary: never leak
            raise AIProviderError(f"fake chat failed: {exc}", provider="fake") from exc

        if not stream:
            return answer

        async def _deltas() -> AsyncIterator[str]:
            words = answer.split(" ")
            for index, word in enumerate(words):
                yield word + (" " if index < len(words) - 1 else "")

        return _deltas()

    async def count_tokens(self, text: str) -> int:
        """Advisory token estimate (shared heuristic, research R4)."""
        return estimate_tokens(text)
