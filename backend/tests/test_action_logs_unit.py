"""Unit tests for the action log service (specs/016-user-action-logs).

Covers the write-once taxonomy, the best-effort SAVEPOINT recording contract
(spec FR-004 — a failing insert must never abort the caller's transaction),
trace truncation, and the list-query assembly (contracts/logs.md §1-2).
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

import pytest

from app.services.action_logs import (
    ACTION_TYPES,
    ERROR_TRACE_MAX_CHARS,
    _build_list_query,
    list_events,
    record_event,
    truncate_trace,
)


@dataclass
class FakeNested:
    async def __aenter__(self) -> "FakeNested":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


@dataclass
class FakeDB:
    fail: bool = False
    calls: list[tuple[object, dict]] = field(default_factory=list)

    def begin_nested(self) -> FakeNested:
        return FakeNested()

    async def execute(self, stmt: object, params: dict) -> None:
        if self.fail:
            raise RuntimeError("log insert failed")
        self.calls.append((stmt, params))


def test_taxonomy_matches_contract() -> None:
    assert ACTION_TYPES == {
        "upload",
        "replace",
        "delete",
        "cancel",
        "reprocess",
        "superseded",
        "restored",
        "processing_started",
        "processing_succeeded",
        "processing_failed",
    }


def test_record_event_inserts_with_owner_scope() -> None:
    db = FakeDB()
    asyncio.run(
        record_event(
            db,
            user_id="user-1",
            action_type="upload",
            filename="a.pdf",
            document_id="doc-1",
            metadata={"file_size_bytes": 10},
        )
    )
    assert len(db.calls) == 1
    _, params = db.calls[0]
    assert params["user_id"] == "user-1"
    assert params["document_id"] == "doc-1"
    assert params["filename"] == "a.pdf"
    assert params["action_type"] == "upload"
    assert params["outcome"] == "succeeded"
    assert params["error_message"] is None
    assert params["metadata"] == '{"file_size_bytes": 10}'


def test_record_event_best_effort_on_insert_failure() -> None:
    """FR-004: a failed log write must not raise — the action survives."""
    db = FakeDB(fail=True)
    asyncio.run(
        record_event(
            db, user_id="user-1", action_type="delete", filename="a.pdf"
        )
    )
    assert db.calls == []


def test_record_event_ignores_unknown_action_type() -> None:
    db = FakeDB()
    asyncio.run(
        record_event(db, user_id="user-1", action_type="magic", filename="a.pdf")
    )
    assert db.calls == []


def test_record_event_truncates_trace() -> None:
    db = FakeDB()
    trace = "x" * (ERROR_TRACE_MAX_CHARS + 500)
    asyncio.run(
        record_event(
            db,
            user_id="user-1",
            action_type="processing_failed",
            filename="a.pdf",
            outcome="failed",
            error_message="boom",
            error_trace=trace,
        )
    )
    _, params = db.calls[0]
    assert params["outcome"] == "failed"
    assert params["error_message"] == "boom"
    assert len(params["error_trace"]) == ERROR_TRACE_MAX_CHARS + len("\n… (truncated)")


def test_truncate_trace_short_trace_untouched() -> None:
    assert truncate_trace("short") == "short"
    assert truncate_trace(None) is None


def test_build_list_query_no_filters() -> None:
    query, params = _build_list_query(action_type=None, from_ts=None, to_ts=None)
    assert "order by created_at desc, id desc" in query.text
    assert "offset :offset" in query.text
    assert "limit :limit" in query.text
    assert params == {}


def test_build_list_query_filters() -> None:
    query, params = _build_list_query(
        action_type="upload",
        from_ts=datetime.fromisoformat("2026-08-01T00:00:00"),
        to_ts=datetime.fromisoformat("2026-08-20T23:59:59"),
    )
    assert "action_type = :action_type" in query.text
    assert "created_at >= :from_ts" in query.text
    assert "created_at <= :to_ts" in query.text
    assert params["action_type"] == "upload"


def test_list_events_best_effort_on_query_failure() -> None:
    """The list path must not swallow: a broken query surfaces to the caller."""

    class BrokenDB(FakeDB):
        async def execute(self, stmt: object, params: dict[str, object]) -> None:
            raise RuntimeError("db down")

    db = BrokenDB()
    with pytest.raises(RuntimeError):
        asyncio.run(list_events(db, "user-1"))
