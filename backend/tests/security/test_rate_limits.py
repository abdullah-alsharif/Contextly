"""Distinct per-user rate-limit budgets: chat (30/min) vs general (120/min).

Covers spec SC-002 and docs/security.md §5: over-limit traffic gets 429 with
`Retry-After`; one budget being exhausted never throttles the other; traffic
under the cap is unaffected. Apps are built per-scenario with tiny limits so
the buckets saturate in a handful of requests, without sleeping.

DB-gated (tests/security/_harness.py) because the endpoints resolve the
identity through the RLS-scoped DB session.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from tests.security import _harness

pytestmark = _harness.DB_GATE

USER = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

# A deliberately absurd conversation id: chat 429 fires in the dependency layer
# before any ownership logic, so the id never needs to exist.
FOREIGN_CONVERSATION = uuid.uuid4()


def _token() -> str:
    return _harness.token(USER)


@pytest.fixture(scope="module")
def make_client(tmp_path_factory: pytest.TempPathFactory):
    """Build an app with the given chat/general limits (fresh buckets each time)."""

    def _build(*, general: int, chat: int) -> TestClient:
        return _harness.make_client(
            str(tmp_path_factory.mktemp("storage")),
            general_budget=general,
            chat_budget=chat,
        )

    return _build


def _general_hit(client: TestClient) -> int:
    """One general-bucket request; returns its status."""

    return client.get(
        "/api/v1/documents", headers={"Authorization": f"Bearer {_token()}"}
    ).status_code


def _chat_hit(client: TestClient) -> int:
    """One chat-bucket request; returns its status (404 until the bucket drains)."""

    return client.post(
        f"/api/v1/conversations/{FOREIGN_CONVERSATION}/messages",
        headers={"Authorization": f"Bearer {_token()}"},
        json={"content": "hello"},
    ).status_code


def test_general_burst_hits_429_with_retry_after(make_client) -> None:
    client = make_client(general=2, chat=1_000_000)
    assert _general_hit(client) == 200
    assert _general_hit(client) == 200
    response = client.get(
        "/api/v1/documents", headers={"Authorization": f"Bearer {_token()}"}
    )
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert int(response.headers["Retry-After"]) >= 1


def test_chat_burst_hits_429_with_retry_after(make_client) -> None:
    client = make_client(general=1_000_000, chat=2)
    # The first two requests pass the limiter and reach the (404) handler.
    assert _chat_hit(client) == 404
    assert _chat_hit(client) == 404
    response = client.post(
        f"/api/v1/conversations/{FOREIGN_CONVERSATION}/messages",
        headers={"Authorization": f"Bearer {_token()}"},
        json={"content": "hello"},
    )
    assert response.status_code == 429
    assert "Retry-After" in response.headers


def test_exhausted_general_does_not_throttle_chat(make_client) -> None:
    client = make_client(general=2, chat=1_000_000)
    assert _general_hit(client) == 200
    assert _general_hit(client) == 200
    assert _general_hit(client) == 429  # general bucket drained
    # Chat budget is independent: the request passes the limiter (404 = reached
    # the handler), never 429.
    assert _chat_hit(client) == 404


def test_exhausted_chat_does_not_throttle_general(make_client) -> None:
    client = make_client(general=1_000_000, chat=2)
    assert _chat_hit(client) == 404
    assert _chat_hit(client) == 404
    assert _chat_hit(client) == 429  # chat bucket drained
    # General budget is independent.
    assert _general_hit(client) == 200


def test_legitimate_traffic_under_limits_unaffected(make_client) -> None:
    client = make_client(general=1_000_000, chat=1_000_000)
    assert _general_hit(client) == 200
    assert _general_hit(client) == 200
    response = client.get(
        "/api/v1/conversations", headers={"Authorization": f"Bearer {_token()}"}
    )
    assert response.status_code == 200
    assert _chat_hit(client) == 404


def test_anonymous_requests_never_consume_buckets(make_client) -> None:
    client = make_client(general=2, chat=1_000_000)
    for _ in range(10):
        assert client.get("/api/v1/documents").status_code == 401
    # Buckets untouched: an authenticated request still succeeds.
    assert _general_hit(client) == 200