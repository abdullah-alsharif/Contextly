"""Action log service: best-effort event recording + tenant-scoped list query.

Recording is best-effort (spec FR-004): record_event wraps the INSERT in a
SAVEPOINT and swallows any failure with a warning, so a log write can never
fail or change the outcome of the action it records. All queries are scoped by
user_id under the RLS session established by get_current_user or the worker's
_switch_to_owner claim (docs/multi-tenancy.md §2).
"""

from __future__ import annotations

import json
from datetime import datetime
from logging import getLogger
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = getLogger(__name__)

ACTION_TYPES = frozenset(
    {
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
)

ERROR_TRACE_MAX_CHARS = 8192

_INSERT_EVENT = text(
    """
    insert into action_logs
        (user_id, action_type, document_id, filename, outcome,
         error_message, error_trace, metadata)
    values (:user_id, :action_type, :document_id, :filename, :outcome,
            :error_message, :error_trace, :metadata)
    """
)

_LIST_EVENTS_BASE = text(
    """
    select id, action_type, outcome, filename, document_id,
           error_message, error_trace, metadata, created_at
    from action_logs
    where user_id = :user_id
    """
)

_LIST_EVENTS_ORDER = " order by created_at desc, id desc offset :offset limit :limit"

_LIST_EVENTS_TYPE = " and action_type = :action_type"
_LIST_EVENTS_FROM = " and created_at >= :from_ts"
_LIST_EVENTS_TO = " and created_at <= :to_ts"


def truncate_trace(
    trace: str | None, max_chars: int = ERROR_TRACE_MAX_CHARS
) -> str | None:
    if trace is None:
        return None
    if len(trace) <= max_chars:
        return trace
    return trace[:max_chars] + "\n… (truncated)"


async def record_event(
    db: AsyncSession,
    *,
    user_id: Any,
    action_type: str,
    filename: str,
    document_id: Any = None,
    outcome: str = "succeeded",
    error_message: str | None = None,
    error_trace: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record one event best-effort (spec FR-004): a failing insert can never
    abort the caller's transaction."""
    if action_type not in ACTION_TYPES:
        logger.warning("skipping unknown action_type %r", action_type)
        return
    try:
        async with db.begin_nested():
            await db.execute(
                _INSERT_EVENT,
                {
                    "user_id": str(user_id),
                    "action_type": action_type,
                    "document_id": str(document_id) if document_id else None,
                    "filename": filename,
                    "outcome": outcome,
                    "error_message": error_message,
                    "error_trace": (
                        truncate_trace(error_trace) if error_trace else None
                    ),
                    "metadata": (
                        json.dumps(metadata) if metadata is not None else "{}"
                    ),
                },
            )
    except Exception:  # noqa: BLE001 - recording must never break the action
        logger.warning(
            "action log write failed for %s (user %s) — recording is best-effort",
            action_type,
            user_id,
            exc_info=True,
        )


def _build_list_query(
    *, action_type: str | None, from_ts: datetime | None, to_ts: datetime | None
) -> tuple[Any, dict[str, Any]]:
    where = ""
    params: dict[str, Any] = {}
    if action_type is not None:
        where += _LIST_EVENTS_TYPE
        params["action_type"] = action_type
    if from_ts is not None:
        where += _LIST_EVENTS_FROM
        params["from_ts"] = from_ts
    if to_ts is not None:
        where += _LIST_EVENTS_TO
        params["to_ts"] = to_ts
    query = text((_LIST_EVENTS_BASE.text or "") + where + _LIST_EVENTS_ORDER)
    return query, params


async def list_events(
    db: AsyncSession,
    user_id: Any,
    *,
    action_type: str | None = None,
    from_: datetime | None = None,
    to: datetime | None = None,
    offset: int = 0,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query, params = _build_list_query(
        action_type=action_type, from_ts=from_, to_ts=to
    )
    params["user_id"] = str(user_id)
    params["offset"] = offset
    params["limit"] = limit
    result = await db.execute(query, params)
    return [_serialize(row) for row in result.all()]


def _serialize(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "action_type": row.action_type,
        "outcome": row.outcome,
        "filename": row.filename,
        "document_id": row.document_id,
        "error_message": row.error_message,
        "error_trace": row.error_trace,
        "metadata": row.metadata,
        "created_at": row.created_at,
    }
