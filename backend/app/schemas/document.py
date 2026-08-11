"""Pydantic schemas for documents (contracts/documents.md §3, docs/api.md §2)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    """Document as returned by the documents API.

    user_id and storage_path are never serialized (docs/multi-tenancy.md §4).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    status: str
    file_size_bytes: int
    total_chunks: int | None
    status_error: str | None
    created_at: datetime
    updated_at: datetime
