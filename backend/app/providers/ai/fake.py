"""FakeProvider: deterministic, zero-credential, offline embeddings.

Contract: specs/006-document-embeddings/contracts/ai-provider.md §3, following
docs/ai-providers.md §2 ("FakeProvider (deterministic embeddings + canned
answers) exists for tests and offline development — no API key, no cost, no
flakiness in CI"). Purely stdlib: SHA-256 of the text seeds a `random.Random`,
so the same text always yields the same vector and no dependencies are added
(research.md R6). Dev/CI only — the factory refuses to build it outside a dev
environment (contracts/ai-provider.md §4).
"""
from __future__ import annotations

import hashlib
import random

from app.providers.ai.base import AIProviderError


class FakeProvider:
    """Deterministic embedding provider for dev and tests (offline, no keys)."""

    embedding_model = "fake-embedding"

    def __init__(self, embedding_dims: int = 1024):
        self.embedding_dims = embedding_dims

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        rng = random.Random(digest)
        return [rng.uniform(-1.0, 1.0) for _ in range(self.embedding_dims)]

    async def embed(
        self, texts: list[str], *, batch_size: int = 32
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
