"""Unit tests for SlidingWindowRateLimiter (docs/security.md §5).

No database: pure in-process behavior with a monkeypatched monotonic clock.
Covers the documented contract precisely — burst => 429-equivalent retry_after,
bounded memory (idle users pruned on sweep), and recovery after the window
elapses (legitimate traffic is never throttled next minute).
"""

from __future__ import annotations

import importlib

import pytest

MOD = importlib.import_module("app.api.dependencies")


class _Clock:
    """Deterministic substitute for time.monotonic."""

    def __init__(self, start: float) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def limiter(monkeypatch: pytest.MonkeyPatch):
    clock = _Clock(1000.0)
    monkeypatch.setattr(MOD.time, "monotonic", clock)
    return MOD.SlidingWindowRateLimiter(per_minute=2), clock


def test_burst_returns_retry_after(limiter) -> None:
    rl, _clock = limiter
    assert rl.check("u") is None
    assert rl.check("u") is None
    retry_after = rl.check("u")  # over the 2/min cap
    assert retry_after is not None
    assert retry_after > 0


def test_retry_after_counts_down_then_allows(limiter) -> None:
    rl, clock = limiter
    assert rl.check("u") is None
    assert rl.check("u") is None
    retry_after = rl.check("u")
    assert retry_after is not None
    # After the window elapses the same user is allowed again.
    clock.now += MOD.WINDOW_SECONDS + 1
    assert rl.check("u") is None


def test_ids_have_independent_budgets(limiter) -> None:
    rl, _clock = limiter
    assert rl.check("a") is None
    assert rl.check("a") is None
    assert rl.check("a") is not None  # a exhausted
    assert rl.check("b") is None  # b unaffected


def test_idle_windows_are_pruned_for_bounded_memory(limiter) -> None:
    rl, clock = limiter
    rl.check("u1")
    rl.check("u2")
    assert set(rl._windows) == {"u1", "u2"}
    # Both users' newest hits age out of the window; the next sweep must drop
    # their entries so the map cannot grow without bound.
    clock.now += MOD.WINDOW_SECONDS * 2
    rl._sweep(clock.now)
    assert rl._windows == {}
    # A returning user gets a fresh window and works normally.
    assert rl.check("u1") is None
    assert set(rl._windows) == {"u1"}


def test_active_user_survives_sweep(limiter) -> None:
    rl, clock = limiter
    rl.check("hot")
    clock.now += 30  # still inside the window
    rl._sweep(clock.now)
    assert "hot" in rl._windows