"""Shared API dependencies: per-user chat rate limiting (docs/security.md §5).

The documented control is an in-process token bucket per user id
(e.g. 30 req/min chat traffic) returning 429 with `Retry-After` on overflow
(research R11). A sliding window keeps the burst behavior simple and
dependency-free: a monotonically growing timestamp queue per user, pruned
against a fixed window. Single-process by design — horizontal-scale
rate limiting is explicitly out of MVP scope (docs/security.md §5).

The limiter instance lives on `app.state` (mirroring the AI/storage providers)
so tests can inject a fresh or high-limit instance via `create_app`.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request

from app.core.security.deps import get_current_user
from app.core.security.identity import Identity

WINDOW_SECONDS = 60.0


@dataclass
class _Window:
    """Sliding-window request log for one user (monotonic timestamps)."""

    hits: deque[float] = field(default_factory=deque)


class ChatRateLimiter:
    """In-process sliding-window limiter keyed by user id (docs/security.md §5)."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._windows: dict[str, _Window] = defaultdict(_Window)
        self._last_sweep = 0.0

    def check(self, user_id: str) -> float | None:
        """Record one hit; return seconds until retry when over the limit."""
        now = time.monotonic()
        self._sweep(now)
        window = self._windows[user_id]
        cutoff = now - WINDOW_SECONDS
        while window.hits and window.hits[0] <= cutoff:
            window.hits.popleft()
        if len(window.hits) >= self.per_minute:
            return WINDOW_SECONDS - (now - window.hits[0])
        window.hits.append(now)
        return None

    def _sweep(self, now: float) -> None:
        """Drop per-user windows that have gone idle (bounded memory).

        Runs at most once per window: entries whose deque is empty (pruned by
        the cutoff) are removed, so the map only holds users active within
        the last window instead of growing without bound.
        """
        if now - self._last_sweep < WINDOW_SECONDS:
            return
        self._last_sweep = now
        idle = [user for user, window in self._windows.items() if not window.hits]
        for user in idle:
            del self._windows[user]


def get_chat_rate_limiter(request: Request) -> ChatRateLimiter:
    """The app-scoped chat rate limiter (injectable in tests via create_app)."""
    limiter: ChatRateLimiter = request.app.state.chat_rate_limiter
    return limiter


class InFlightRegistry:
    """In-process set of idempotency keys with an active SSE stream.

    The original send is "in flight" from the moment its user message is
    committed until the stream ends (contracts/chat.md §3): a duplicate with
    the same key in this window → 409. Keyed by `conversation_id|key` so the
    same key in two conversations never collides. Single-process by design,
    mirroring the chat rate limiter (docs/security.md §5).

    Narrow best-effort race (research R3, MVP-acceptable): a duplicate whose
    `prepare_chat` ran before the original stream's assistant commit, but
    whose registry mark lands after the original cleared its key, re-runs the
    pipeline on the same user message and may persist a second assistant row
    (the user row stays deduped; later replays use the oldest answer).
    """

    def __init__(self) -> None:
        self._active: set[str] = set()

    def _key(self, conversation_id: str, key: str) -> str:
        return f"{conversation_id}|{key}"

    def mark(self, conversation_id: str, key: str) -> bool:
        """Mark the key in-flight; False when it already is (→ 409)."""
        token = self._key(conversation_id, key)
        if token in self._active:
            return False
        self._active.add(token)
        return True

    def clear(self, conversation_id: str, key: str) -> None:
        """Release the key; safe to call once per stream (idempotent)."""
        self._active.discard(self._key(conversation_id, key))


def get_in_flight_registry(request: Request) -> InFlightRegistry:
    """The app-scoped in-flight registry (injectable in tests via create_app)."""
    registry: InFlightRegistry = request.app.state.chat_in_flight
    return registry


async def enforce_chat_rate_limit(
    identity: Identity = Depends(get_current_user),
    limiter: ChatRateLimiter = Depends(get_chat_rate_limiter),
) -> None:
    """Dependency: 429 with Retry-After when the user exceeds the chat limit."""
    retry_after = limiter.check(str(identity.user_id))
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="chat rate limit exceeded, retry later",
            headers={"Retry-After": str(max(1, int(retry_after)))},
        )
