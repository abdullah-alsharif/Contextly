"""Logs router: GET /logs returns the caller's action-log entries, newest
first, with optional action_type/from/to filters and offset/limit paging.

Router-level get_current_user + enforce_general_rate_limit match
api/documents.py, so unauthenticated requests get 401 by construction.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import enforce_general_rate_limit
from app.core.security.deps import get_current_user
from app.core.security.identity import Identity
from app.db.session import get_db
from app.schemas.action_log import LogEntryOut
from app.services.action_logs import ACTION_TYPES, list_events

router = APIRouter(
    prefix="/logs",
    tags=["logs"],
    dependencies=[Depends(get_current_user), Depends(enforce_general_rate_limit)],
)


def _parse_bound(
    value: str | None, name: str, *, upper: bool
) -> datetime | None:
    """Parse an ISO 8601 bound; date-only values get UTC day bounds.

    `2026-08-01` means the start of that UTC day for `from` and the end of that
    UTC day for `to`; malformed input → 422.
    """
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"malformed {name} date") from None
    if dt.tzinfo is None:
        if len(value) == 10 and "T" not in value:
            if upper:
                dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt


@router.get("", response_model=list[LogEntryOut])
async def list_logs(
    action_type: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    identity: Identity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, object]]:
    if action_type is not None and action_type not in ACTION_TYPES:
        raise HTTPException(status_code=422, detail="unknown action_type")
    from_ts = _parse_bound(from_, "from", upper=False)
    to_ts = _parse_bound(to, "to", upper=True)
    if from_ts is not None and to_ts is not None and to_ts < from_ts:
        raise HTTPException(status_code=422, detail="to must not be before from")
    return await list_events(
        db,
        identity.user_id,
        action_type=action_type,
        from_=from_ts,
        to=to_ts,
        offset=offset,
        limit=limit,
    )
