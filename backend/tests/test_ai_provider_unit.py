"""AIProvider unit matrix: fake determinism, factory, startup guards, retries.

No DB, no network: real HTTP providers are driven through httpx.MockTransport
(research.md R7, quickstart VS-2/VS-3/VS-4/VS-5). Retry backoffs are overridden
to zero in tests so the matrix stays fast.
"""
from __future__ import annotations

import asyncio
import json
from typing import Callable

import httpx
import pytest

from app.core.config import Settings
from app.providers.ai import build_ai_provider
from app.providers.ai.base import AIProvider, AIProviderError, validate_dimension
from app.providers.ai.fake import FakeProvider
from app.providers.ai.nvidia import NvidiaProvider
from app.providers.ai.openrouter import OpenRouterProvider

NO_BACKOFF = (0.0, 0.0)

Handler = Callable[[httpx.Request], httpx.Response]


def _settings(**overrides) -> Settings:
    defaults = {"auth_mode": "dev", "app_env": "dev"}
    defaults.update(overrides)
    return Settings(**defaults)


def _vector_embedding(index: int) -> list[float]:
    return [float(index) + 1.0] + [0.0] * 1022 + [1.0]


def _ok_payload(texts: list[str]) -> dict:
    return {
        "data": [
            {"object": "embedding", "index": i, "embedding": _vector_embedding(i)}
            for i in range(len(texts))
        ],
        "model": "test-model",
        "object": "list",
    }


# ---------------------------------------------------------------------------
# Fake provider (US2 AC1; contracts §3)
# ---------------------------------------------------------------------------


def test_fake_provider_is_deterministic_and_offline() -> None:
    provider = FakeProvider(embedding_dims=1024)
    first = asyncio.run(provider.embed(["alpha", "beta"]))
    second = asyncio.run(provider.embed(["alpha", "beta"]))
    assert first == second  # deterministic
    assert len(first) == 2
    assert len(first[0]) == 1024
    assert all(-1.0 <= value <= 1.0 for value in first[0])
    assert first[0] != first[1]  # distinct texts → distinct vectors
    assert asyncio.run(provider.embed([])) == []  # empty input → no-op


# ---------------------------------------------------------------------------
# Factory + startup validation (US2 AC1-5, US3 AC1; quickstart VS-2/VS-3/VS-5)
# ---------------------------------------------------------------------------


def test_factory_selects_fake_by_default() -> None:
    provider = build_ai_provider(_settings(ai_provider="fake"))
    assert isinstance(provider, FakeProvider)
    assert provider.embedding_dims == 1024
    assert provider.embedding_model == "fake-embedding"


def test_factory_selects_nvidia_and_openrouter() -> None:
    nvidia = build_ai_provider(_settings(ai_provider="nvidia"))
    assert isinstance(nvidia, NvidiaProvider)
    assert nvidia.embedding_model == "nvidia/bge-m3"
    assert nvidia.embedding_dims == 1024

    openrouter = build_ai_provider(_settings(ai_provider="openrouter"))
    assert isinstance(openrouter, OpenRouterProvider)
    assert openrouter.embedding_model == "openai/text-embedding-3-small"
    assert openrouter.embedding_dims == 1024


def test_factory_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="ai_provider must be"):
        build_ai_provider(_settings(ai_provider="bogus"))


def test_fake_provider_is_refused_outside_dev() -> None:
    with pytest.raises(RuntimeError, match="AI_PROVIDER=fake is only allowed"):
        build_ai_provider(_settings(ai_provider="fake", app_env="production"))


def test_dimension_mismatch_fails_fast() -> None:
    # nvidia reports a fixed 1024; a DB column configured at 768 must abort startup.
    with pytest.raises(RuntimeError, match="embedding_dims=1024.*vector\\(768\\)"):
        build_ai_provider(_settings(ai_provider="nvidia", embedding_dim=768))
    with pytest.raises(RuntimeError, match="768"):
        validate_dimension(FakeProvider(embedding_dims=768), 1024, "fake")


# ---------------------------------------------------------------------------
# NVIDIA provider via MockTransport (request shape + order preservation)
# ---------------------------------------------------------------------------


def _nvidia_provider(handler: Handler) -> NvidiaProvider:
    transport = httpx.MockTransport(handler)
    return NvidiaProvider(
        api_key="test-key",
        retries=2,
        backoff_seconds=NO_BACKOFF,
        transport=transport,
    )


def test_nvidia_requests_shape_and_parses_order_preserved() -> None:
    received: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        payload = json.loads(request.content)
        return httpx.Response(200, json=_ok_payload(payload["input"]))

    provider = _nvidia_provider(handler)
    vectors = asyncio.run(provider.embed(["first", "second", "third"], batch_size=2))

    assert len(received) == 2  # batched: [first, second] then [third]
    assert received[0].url == "https://integrate.api.nvidia.com/v1/embeddings"
    assert received[0].headers["Authorization"] == "Bearer test-key"
    payload = {"model": "nvidia/bge-m3", "input": ["first", "second"]}
    assert json.loads(received[0].content) == payload
    # order preserved: batch 1 indices 0,1 then batch 2 index 0 (per-batch indices)
    assert vectors[0][0] == 1.0 and vectors[1][0] == 2.0 and vectors[2][0] == 1.0
    assert all(len(v) == 1024 for v in vectors)


def test_nvidia_retries_5xx_then_surfaces_error() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, text="overloaded")

    provider = _nvidia_provider(handler)
    with pytest.raises(AIProviderError) as excinfo:
        asyncio.run(provider.embed(["text"]))
    assert attempts == 3  # initial + 2 retries
    assert excinfo.value.status_code == 503
    assert excinfo.value.provider == "nvidia"


def test_nvidia_recovers_after_transient_5xx() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(500, text="boom")
        payload = json.loads(request.content)
        return httpx.Response(200, json=_ok_payload(payload["input"]))

    provider = _nvidia_provider(handler)
    vectors = asyncio.run(provider.embed(["text"]))
    assert attempts == 2
    assert len(vectors) == 1 and len(vectors[0]) == 1024


def test_nvidia_does_not_retry_401_or_403() -> None:
    for status in (401, 403):
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(status, text="unauthorized")

        provider = _nvidia_provider(handler)
        with pytest.raises(AIProviderError) as excinfo:
            asyncio.run(provider.embed(["text"]))
        assert attempts == 1  # configuration error → never retried
        assert excinfo.value.status_code == status


def test_nvidia_honors_retry_after_on_429() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429, headers={"Retry-After": "0"}, text="slow down"
            )
        payload = json.loads(request.content)
        return httpx.Response(200, json=_ok_payload(payload["input"]))

    provider = _nvidia_provider(handler)
    vectors = asyncio.run(provider.embed(["text"]))
    assert attempts == 2
    assert len(vectors) == 1


def test_nvidia_surfaces_rate_limit_when_never_resolves() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"}, text="slow down")

    provider = _nvidia_provider(handler)
    with pytest.raises(AIProviderError) as excinfo:
        asyncio.run(provider.embed(["text"]))
    assert excinfo.value.status_code == 429


def test_nvidia_retries_network_errors() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("connection refused")
        payload = json.loads(request.content)
        return httpx.Response(200, json=_ok_payload(payload["input"]))

    provider = _nvidia_provider(handler)
    vectors = asyncio.run(provider.embed(["text"]))
    assert attempts == 2
    assert len(vectors) == 1


def test_nvidia_rejects_wrong_shaped_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"object": "embedding", "index": 0, "embedding": [1.0]}]},
        )

    provider = _nvidia_provider(handler)
    with pytest.raises(AIProviderError, match="has 1 dims"):
        asyncio.run(provider.embed(["text"]))


def test_nvidia_rejects_missing_vectors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    provider = _nvidia_provider(handler)
    with pytest.raises(AIProviderError, match="count 0 != input count 1"):
        asyncio.run(provider.embed(["text"]))


# ---------------------------------------------------------------------------
# OpenRouter provider: dimensions parameter + model
# ---------------------------------------------------------------------------


def test_openrouter_sends_dimensions_1024() -> None:
    received: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["payload"] = json.loads(request.content)
        received["url"] = str(request.url)
        received["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json=_ok_payload(["text"]))

    provider = OpenRouterProvider(
        api_key="or-key",
        retries=2,
        backoff_seconds=NO_BACKOFF,
        transport=httpx.MockTransport(handler),
    )
    vectors = asyncio.run(provider.embed(["text"]))
    assert len(vectors) == 1 and len(vectors[0]) == 1024
    assert received["url"] == "https://openrouter.ai/api/v1/embeddings"
    assert received["auth"] == "Bearer or-key"
    assert received["payload"] == {
        "model": "openai/text-embedding-3-small",
        "input": ["text"],
        "dimensions": 1024,
    }


# ---------------------------------------------------------------------------
# Empty-input contracts shared by all providers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", [
    FakeProvider(embedding_dims=1024),
    NvidiaProvider(api_key="k", retries=2, backoff_seconds=NO_BACKOFF),
    OpenRouterProvider(api_key="k", retries=2, backoff_seconds=NO_BACKOFF),
])
def test_empty_input_is_a_noop(provider: AIProvider) -> None:
    assert asyncio.run(provider.embed([])) == []
