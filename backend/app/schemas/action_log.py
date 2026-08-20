"""Pydantic schemas for action logs (contracts/logs.md §2)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LogEntryOut(BaseModel):
    """One recorded event as returned by GET /logs.

    user_id and storage_path are never serialized; error fields are null for
    success (docs/multi-tenancy.md §4, contracts/logs.md §3).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action_type: str
    outcome: str
    filename: str
    document_id: uuid.UUID | None
    error_message: str | None
    error_trace: str | None
    metadata: dict[str, object]
    created_at: datetime
