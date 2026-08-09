"""Pydantic schemas for profiles (contracts/auth.md §6)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProfileOut(BaseModel):
    """Profile as returned by GET /auth/me."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None
    created_at: datetime
    updated_at: datetime
