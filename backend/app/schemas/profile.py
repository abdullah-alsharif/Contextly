"""Pydantic schemas for profiles (contracts/auth.md §6)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_FULL_NAME_CHARS = 120


class ProfileOut(BaseModel):
    """Profile as returned by GET/PATCH /auth/me."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None
    created_at: datetime
    updated_at: datetime


class ProfileIn(BaseModel):
    """PATCH /auth/me body: the display name (optional, trimmed, ≤120 chars)."""

    full_name: str | None = Field(default=None, max_length=MAX_FULL_NAME_CHARS)

    @field_validator("full_name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value
