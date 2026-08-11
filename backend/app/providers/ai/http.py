"""Shared HTTP helper for OpenAI-compatible embeddings + chat endpoints.

NVIDIA NIM Build and OpenRouter both expose OpenAI-compatible endpoints, so
this module owns the HTTP calls, the retry/backoff policy (docs/ai-providers.md
§4, contracts/ai-provider.md §5), and response parsing — vendors only supply
URL, key, model, and dimensions.

Retry policy:
- network errors/timeouts and 5xx → retry with backoff up to `retries`;
- 429 → retry honoring the Retry-After header when present, else backoff;
- 401/403 (and other 4xx) → never retried (configuration/request errors);
- malformed or wrong-shaped responses → raise immediately (provider bug).

Every failure surfaces as AIProviderError with provider + status attached.
"""

from __future__ import annotations

import asyncio
import email.utils
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import httpx

from app.providers.ai.base import AIProviderError

DEFAULT_TIMEOUT_SECONDS = 60.0

_STREAM_DONE = "[DONE]"


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Retry-After header as seconds; supports both delta and HTTP-date."""
    value = response.headers.get("Retry-After")
    if not value:
        return None
    if value.isdigit():
        return float(value)
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())


async def post_embeddings(
    *,
    url: str,
    api_key: str,
    model: str,
    provider_name: str,
    texts: list[str],
    embedding_dims: int,
    dimensions: int | None = None,
    retries: int = 3,
    backoff_seconds: tuple[float, ...] = (1.0, 2.0, 4.0),
    transport: httpx.AsyncBaseTransport | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[list[float]]:
    """POST texts to an OpenAI-compatible embeddings endpoint.

    Returns one vector per input text, in order. Raises AIProviderError on any
    failure (contracts/ai-provider.md §5).
    """
    body: dict[str, object] = {"model": model, "input": texts}
    if dimensions is not None:
        body["dimensions"] = dimensions

    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(
                transport=transport, timeout=timeout_seconds
            ) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
        except httpx.HTTPError as exc:
            if attempt < retries:
                await asyncio.sleep(
                    backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                )
                continue
            raise AIProviderError(
                f"embedding request failed: {exc}",
                provider=provider_name,
                status_code=None,
            ) from exc

        if response.status_code == 429:
            if attempt < retries:
                wait = (
                    _retry_after_seconds(response)
                    or backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                )
                await asyncio.sleep(wait)
                continue
            raise AIProviderError(
                f"embedding rate limited (429): {response.text[:200]}",
                provider=provider_name,
                status_code=429,
            )
        if response.status_code >= 500:
            if attempt < retries:
                await asyncio.sleep(
                    backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                )
                continue
            raise AIProviderError(
                f"embedding provider error ({response.status_code}): "
                f"{response.text[:200]}",
                provider=provider_name,
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise AIProviderError(
                f"embedding request rejected ({response.status_code}): "
                f"{response.text[:200]}",
                provider=provider_name,
                status_code=response.status_code,
            )

        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - vendor junk must not escape
            raise AIProviderError(
                f"unparseable embedding response: {exc}",
                provider=provider_name,
                status_code=response.status_code,
            ) from exc
        return _parse_embeddings(payload, texts, embedding_dims, provider_name)

    raise AssertionError("unreachable")  # pragma: no cover


def _parse_embeddings(
    payload: object,
    texts: list[str],
    embedding_dims: int,
    provider_name: str,
) -> list[list[float]]:
    """Extract order-preserving vectors from an OpenAI-style embeddings payload."""
    try:
        items = payload["data"]  # type: ignore[index]
        rows = sorted(items, key=lambda item: item["index"])
        vectors = [list(row["embedding"]) for row in rows]
    except Exception as exc:  # noqa: BLE001 - any shape violation is a provider bug
        raise AIProviderError(
            f"malformed embedding response: {exc}",
            provider=provider_name,
            status_code=None,
        ) from exc
    if len(vectors) != len(texts):
        raise AIProviderError(
            f"embedding response count {len(vectors)} != input count {len(texts)}",
            provider=provider_name,
            status_code=None,
        )
    for index, vector in enumerate(vectors):
        if len(vector) != embedding_dims:
            raise AIProviderError(
                f"embedding vector {index} has {len(vector)} dims, expected "
                f"{embedding_dims}",
                provider=provider_name,
                status_code=None,
            )
    return vectors


async def post_chat(
    *,
    url: str,
    api_key: str,
    model: str,
    provider_name: str,
    messages: list[dict[str, Any]],
    stream: bool = False,
    retries: int = 2,
    backoff_seconds: tuple[float, ...] = (1.0, 2.0),
    transport: httpx.AsyncBaseTransport | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> str | AsyncIterator[str]:
    """POST messages to an OpenAI-compatible chat-completions endpoint.

    Returns the full completion text when stream=False, or an async iterator
    of incremental text deltas when stream=True (research R4). Deltas never
    carry trailing whitespace state beyond what the vendor sends; the caller
    accumulates them into the final text.

    Failures surface as AIProviderError:
    - HTTP status errors before the body (network, 5xx after retries, 429
      after retries, 4xx) — mirroring post_embeddings status handling;
    - vendor `{"error": ...}` chunks mid-stream;
    - malformed JSON lines mid-stream are logged and skipped (research R4).
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async def _stream() -> AsyncIterator[str]:
        try:
            async with httpx.AsyncClient(
                transport=transport, timeout=timeout_seconds
            ) as client:
                async with client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json={"model": model, "messages": messages, "stream": True},
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", "replace")
                        raise AIProviderError(
                            f"chat request rejected ({response.status_code}): "
                            f"{body[:200]}",
                            provider=provider_name,
                            status_code=response.status_code,
                        )
                    saw_terminator = False
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if not payload:
                            continue
                        if payload == _STREAM_DONE:
                            saw_terminator = True
                            return
                        try:
                            chunk = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        if "error" in chunk:
                            raise AIProviderError(
                                f"chat stream error: {chunk['error']}",
                                provider=provider_name,
                                status_code=None,
                            )
                        delta = _extract_stream_delta(chunk, provider_name)
                        if delta:
                            yield delta
                    if not saw_terminator:
                        # A stream that ends without [DONE] was truncated — the
                        # caller must not persist a partial answer as 'done'.
                        raise AIProviderError(
                            "chat stream ended without [DONE] terminator",
                            provider=provider_name,
                            status_code=None,
                        )
        except httpx.HTTPError as exc:
            raise AIProviderError(
                f"chat stream request failed: {exc}",
                provider=provider_name,
                status_code=None,
            ) from exc

    if stream:
        return _stream()

    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(
                transport=transport, timeout=timeout_seconds
            ) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json={"model": model, "messages": messages, "stream": False},
                )
        except httpx.HTTPError as exc:
            if attempt < retries:
                await asyncio.sleep(
                    backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                )
                continue
            raise AIProviderError(
                f"chat request failed: {exc}",
                provider=provider_name,
                status_code=None,
            ) from exc

        if response.status_code == 429:
            if attempt < retries:
                wait = (
                    _retry_after_seconds(response)
                    or backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                )
                await asyncio.sleep(wait)
                continue
            raise AIProviderError(
                f"chat rate limited (429): {response.text[:200]}",
                provider=provider_name,
                status_code=429,
            )
        if response.status_code >= 500:
            if attempt < retries:
                await asyncio.sleep(
                    backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                )
                continue
            raise AIProviderError(
                f"chat provider error ({response.status_code}): {response.text[:200]}",
                provider=provider_name,
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise AIProviderError(
                f"chat request rejected ({response.status_code}): "
                f"{response.text[:200]}",
                provider=provider_name,
                status_code=response.status_code,
            )

        try:
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - vendor junk must not escape
            raise AIProviderError(
                f"unparseable chat response: {exc}",
                provider=provider_name,
                status_code=response.status_code,
            ) from exc
        return _extract_chat_content(payload, provider_name)

    raise AssertionError("unreachable")  # pragma: no cover


def _extract_chat_content(payload: object, provider_name: str) -> str:
    """Extract the completion text from a non-stream OpenAI-style payload."""
    try:
        choices = payload["choices"]  # type: ignore[index]
        content = choices[0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001 - any shape violation is a provider bug
        raise AIProviderError(
            f"malformed chat response: {exc}",
            provider=provider_name,
            status_code=None,
        ) from exc
    if not isinstance(content, str):
        raise AIProviderError(
            "malformed chat response: content is not a string",
            provider=provider_name,
            status_code=None,
        )
    return content


def _extract_stream_delta(chunk: object, provider_name: str) -> str:
    """Extract the incremental text from one streamed SSE chunk."""
    try:
        choices = chunk["choices"]  # type: ignore[index]
        delta = choices[0].get("delta", {}) if choices else {}
        content = delta.get("content")
    except Exception as exc:  # noqa: BLE001 - provider bug must not escape
        raise AIProviderError(
            f"malformed chat stream chunk: {exc}",
            provider=provider_name,
            status_code=None,
        ) from exc
    if content is None:
        return ""
    if not isinstance(content, str):
        raise AIProviderError(
            "malformed chat stream chunk: content is not a string",
            provider=provider_name,
            status_code=None,
        )
    return content
