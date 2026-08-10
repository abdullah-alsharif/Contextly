"""Shared HTTP helper for OpenAI-compatible embeddings endpoints.

NVIDIA NIM Build and OpenRouter both expose an OpenAI-compatible
POST /embeddings (research.md R2), so this module owns the HTTP call, the
retry/backoff policy (docs/ai-providers.md §4, contracts/ai-provider.md §5),
and response parsing — vendors only supply URL, key, model, and dimensions.

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
from datetime import datetime, timezone

import httpx

from app.providers.ai.base import AIProviderError

DEFAULT_TIMEOUT_SECONDS = 60.0


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
                await asyncio.sleep(backoff_seconds[min(attempt, len(backoff_seconds) - 1)])
                continue
            raise AIProviderError(
                f"embedding request failed: {exc}",
                provider=provider_name,
                status_code=None,
            ) from exc

        if response.status_code == 429:
            if attempt < retries:
                wait = _retry_after_seconds(response) or backoff_seconds[
                    min(attempt, len(backoff_seconds) - 1)
                ]
                await asyncio.sleep(wait)
                continue
            raise AIProviderError(
                f"embedding rate limited (429): {response.text[:200]}",
                provider=provider_name,
                status_code=429,
            )
        if response.status_code >= 500:
            if attempt < retries:
                await asyncio.sleep(backoff_seconds[min(attempt, len(backoff_seconds) - 1)])
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
