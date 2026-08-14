"""Pydantic schemas for conversations (Phase 7 chat).

Contract: specs/008-chat-conversations/contracts/chat.md §1, following
docs/api.md §3 (conversation object) and §6 (validation → 422). The live
4000-char question cap is enforced at the endpoint against
`chat_question_max_chars`; the message schemas live in schemas/message.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_DOCUMENT_IDS = 100
MAX_TITLE_CHARS = 200


class ConversationIn(BaseModel):
    """Create/update body: optional title, document selection, pin, archive."""

    title: str | None = Field(default=None, max_length=MAX_TITLE_CHARS)
    document_ids: list[uuid.UUID] | None = Field(
        default=None, max_length=MAX_DOCUMENT_IDS
    )
    pinned: bool | None = None
    archived: bool | None = None

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("title must not be empty")
        return value


class ConversationOut(BaseModel):
    """Conversation as returned by the conversations API (docs/api.md §3)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    pinned: bool
    archived: bool
    created_at: datetime
    updated_at: datetime


class ConversationDetailOut(BaseModel):
    """Detail response: the conversation plus its selected documents."""

    conversation: ConversationOut
    documents: list[Any]
