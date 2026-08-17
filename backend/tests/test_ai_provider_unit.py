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
from app.providers.ai.base import (
    AIProvider,
    AIProviderError,
    EMBED_SAFE_CHARS_PER_TOKEN,
    clamp_chunk_size_chars,
    is_transient_status,
    validate_dimension,
)
from app.providers.ai.fake import FakeProvider
from app.providers.ai.nvidia import NvidiaProvider
from app.providers.ai.openrouter import OpenRouterProvider
from app.services.chunker import CHARS_PER_TOKEN, chunk_pages

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
    assert nvidia.embedding_model == "nvidia/nv-embedqa-e5-v5"
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
# Input-cap policy: status classification + chunk clamping (docs/ai-providers.md §2/§4)
# ---------------------------------------------------------------------------


def test_is_transient_status_classification() -> None:
    assert is_transient_status(None)  # network failure
    assert is_transient_status(429)
    assert is_transient_status(500)
    assert is_transient_status(503)
    assert not is_transient_status(400)  # deterministic rejections
    assert not is_transient_status(401)
    assert not is_transient_status(403)
    assert not is_transient_status(404)
    assert not is_transient_status(422)


def test_clamp_keeps_window_for_caps_above_it() -> None:
    size = round(500 * CHARS_PER_TOKEN)
    assert clamp_chunk_size_chars(size, 8191) == size
    assert clamp_chunk_size_chars(size, 8192) == size


def test_clamp_shrinks_window_to_nvidia_cap() -> None:
    # 512-token cap at the 1.4 chars/token floor ≈ 298 estimated-token windows.
    clamped = clamp_chunk_size_chars(round(500 * CHARS_PER_TOKEN), 512)
    assert clamped == round(512 * EMBED_SAFE_CHARS_PER_TOKEN)
    assert clamped < round(500 * CHARS_PER_TOKEN)


def test_clamp_honors_smaller_windows() -> None:
    assert clamp_chunk_size_chars(round(200 * CHARS_PER_TOKEN), 512) == round(
        200 * CHARS_PER_TOKEN
    )


def test_clamp_bounds_chunk_pages_end_to_end() -> None:
    size = round(500 * CHARS_PER_TOKEN)
    clamped = clamp_chunk_size_chars(size, 512)
    code_page = "int foo = bar(baz);\n" * (clamped // 20 + 2)
    chunks = chunk_pages(
        [code_page], chunk_size_chars=clamped, overlap_chars=round(50 * CHARS_PER_TOKEN)
    )
    assert chunks
    assert all(len(c.content) <= clamped for c in chunks)


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
    # nv-embedqa-e5-v5 is asymmetric: input_type is mandatory (query|passage).
    payload = {
        "model": "nvidia/nv-embedqa-e5-v5",
        "input": ["first", "second"],
        "input_type": "passage",
    }
    assert json.loads(received[0].content) == payload
    # order preserved: batch 1 indices 0,1 then batch 2 index 0 (per-batch indices)
    assert vectors[0][0] == 1.0 and vectors[1][0] == 2.0 and vectors[2][0] == 1.0
    assert all(len(v) == 1024 for v in vectors)


def test_nvidia_embed_forwards_query_input_type() -> None:
    # Retrieval questions embed with input_type="query" (docs/ai-providers.md §2).
    received: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(json.loads(request.content))
        return httpx.Response(200, json=_ok_payload(["question?"]))

    provider = _nvidia_provider(handler)
    asyncio.run(provider.embed(["question?"], input_type="query"))
    assert received[0]["input_type"] == "query"


def test_providers_expose_their_input_caps() -> None:
    # The pipeline clamps chunking to these (docs/ai-providers.md §2).
    assert NvidiaProvider(api_key="k").embedding_max_input_tokens == 512
    assert OpenRouterProvider(api_key="k").embedding_max_input_tokens == 8191
    # Fake never rejects input: its cap must not shrink the tuned 500-token window.
    assert (
        FakeProvider().embedding_max_input_tokens * EMBED_SAFE_CHARS_PER_TOKEN
        >= round(500 * CHARS_PER_TOKEN)
    )


def test_nvidia_truncates_over_cap_text_before_request() -> None:
    # Input past the 512-token cap must not reach the vendor as-is — the
    # backstop truncates to the conservative char floor first.
    cap_chars = round(512 * EMBED_SAFE_CHARS_PER_TOKEN)
    received: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        received.extend(payload["input"])
        return httpx.Response(200, json=_ok_payload(payload["input"]))

    provider = _nvidia_provider(handler)
    long_text = "word " * (cap_chars + 200)
    vectors = asyncio.run(provider.embed(["short", long_text]))
    assert len(vectors) == 2
    assert received[0] == "short"  # in-cap text passes through untouched
    assert received[1] == long_text[:cap_chars]
    assert len(received[1]) == cap_chars


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
            return httpx.Response(429, headers={"Retry-After": "0"}, text="slow down")
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


@pytest.mark.parametrize(
    "provider",
    [
        FakeProvider(embedding_dims=1024),
        NvidiaProvider(api_key="k", retries=2, backoff_seconds=NO_BACKOFF),
        OpenRouterProvider(api_key="k", retries=2, backoff_seconds=NO_BACKOFF),
    ],
)
def test_empty_input_is_a_noop(provider: AIProvider) -> None:
    assert asyncio.run(provider.embed([])) == []


# ---------------------------------------------------------------------------
# Phase 7 chat surface: generate / streaming / count_tokens (research R4)
# ---------------------------------------------------------------------------


_MESSAGES = [
    {"role": "system", "content": "system prompt"},
    {"role": "user", "content": "What is the refund period?"},
]


def test_fake_generate_is_deterministic_and_offline() -> None:
    provider = FakeProvider(embedding_dims=1024)
    assert provider.supports_streaming is True
    assert provider.chat_model == "fake-chat"
    first = asyncio.run(provider.generate(_MESSAGES))
    second = asyncio.run(provider.generate(_MESSAGES))
    assert isinstance(first, str)
    assert first == second  # deterministic canned answer
    assert "What is the refund period?" in first


def test_fake_streaming_deltas_accumulate_to_full_answer() -> None:
    provider = FakeProvider(embedding_dims=1024)
    stream = asyncio.run(provider.generate(_MESSAGES, stream=True))
    assert not isinstance(stream, str)
    collected = "".join(part for part in asyncio.run(_collect(stream)) if part)
    full = asyncio.run(provider.generate(_MESSAGES))
    assert isinstance(full, str)
    assert collected == full


async def _collect(iterator) -> list[str]:
    return [part async for part in iterator]


def test_fake_count_tokens_uses_shared_heuristic() -> None:
    provider = FakeProvider(embedding_dims=1024)
    text = "x" * 40
    assert asyncio.run(provider.count_tokens(text)) == 10  # len // 4


def _chat_payload(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def test_nvidia_generate_non_stream_parses_content() -> None:
    received: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["payload"] = json.loads(request.content)
        received["url"] = str(request.url)
        return httpx.Response(200, json=_chat_payload("The refund period is 30 days."))

    provider = _nvidia_provider(handler)
    answer = asyncio.run(provider.generate(_MESSAGES))
    assert answer == "The refund period is 30 days."
    assert received["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert received["payload"] == {
        "model": "meta/llama-3.3-70b-instruct",
        "messages": _MESSAGES,
        "stream": False,
    }


def _stream_ok_handler() -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            'data: {"choices":[{"delta":{"content":"The "}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"refund"}}]}\n\n'
            'data: {"choices":[{"delta":{}}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(
            200, text=body, headers={"Content-Type": "text/event-stream"}
        )

    return handler


def test_nvidia_generate_stream_accumulates_deltas() -> None:
    provider = _nvidia_provider(_stream_ok_handler())
    stream = asyncio.run(provider.generate(_MESSAGES, stream=True))
    assert not isinstance(stream, str)
    parts = asyncio.run(_collect(stream))
    assert parts == ["The ", "refund"]
    assert "".join(parts) == "The refund"


def test_nvidia_stream_surfaces_vendor_error_chunk() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = 'data: {"error": {"message": "upstream failure"}}\n\n'
        return httpx.Response(200, text=body)

    provider = _nvidia_provider(handler)
    stream = asyncio.run(provider.generate(_MESSAGES, stream=True))
    assert not isinstance(stream, str)
    with pytest.raises(AIProviderError, match="upstream failure"):
        asyncio.run(_collect(stream))


def test_nvidia_stream_rejects_http_status_before_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    provider = _nvidia_provider(handler)
    stream = asyncio.run(provider.generate(_MESSAGES, stream=True))
    assert not isinstance(stream, str)
    with pytest.raises(AIProviderError) as excinfo:
        asyncio.run(_collect(stream))
    assert excinfo.value.status_code == 500


def test_nvidia_chat_retries_5xx_then_surfaces_error() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, text="overloaded")

    provider = _nvidia_provider(handler)
    with pytest.raises(AIProviderError) as excinfo:
        asyncio.run(provider.generate(_MESSAGES))
    assert attempts == 3  # initial + 2 retries (nvidia retries=2)
    assert excinfo.value.status_code == 503


def test_nvidia_chat_does_not_retry_401() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, text="bad key")

    provider = _nvidia_provider(handler)
    with pytest.raises(AIProviderError) as excinfo:
        asyncio.run(provider.generate(_MESSAGES))
    assert attempts == 1  # configuration error → never retried
    assert excinfo.value.status_code == 401


def test_openrouter_chat_request_shape() -> None:
    received: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["payload"] = json.loads(request.content)
        received["url"] = str(request.url)
        return httpx.Response(200, json=_chat_payload("ok"))

    provider = OpenRouterProvider(
        api_key="or-key",
        retries=2,
        backoff_seconds=NO_BACKOFF,
        transport=httpx.MockTransport(handler),
    )
    answer = asyncio.run(provider.generate(_MESSAGES))
    assert answer == "ok"
    assert received["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert received["payload"] == {
        "model": "openai/gpt-4o-mini",
        "messages": _MESSAGES,
        "stream": False,
    }
    assert provider.supports_streaming is True
    assert asyncio.run(provider.count_tokens("x" * 40)) == 10
