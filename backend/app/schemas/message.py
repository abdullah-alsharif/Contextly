"""Pydantic schemas for messages (Phase 7 chat).

Contract: specs/008-chat-conversations/contracts/chat.md §2-3, following
docs/api.md §4 (message object, SSE payloads) and docs/security.md §4
(question length cap). The live 4000-char cap is enforced at the endpoint
against `chat_question_max_chars`; this schema only applies a generous
structural bound so request bodies stay bounded even if an operator raises
the cap (mirrors `RagQueryIn` in schemas/retrieval.py).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_CONTENT_CHARS = 10000


class MessageOut(BaseModel):
    """Message as returned by history (docs/api.md §4).

    `sources` is a JSON snapshot on assistant rows (docs/rag.md §5); `status`
    is 'error' on partial assistant messages persisted after a mid-stream
    provider failure (docs/chat.md §6).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    sources: list[dict[str, Any]] | None
    status: str
    input_tokens: int | None
    output_tokens: int | None
    retrieval_ms: int | None
    llm_ms: int | None
    created_at: datetime


class MessageSendIn(BaseModel):
    """Send body: the question (trimmed; live cap enforced at the endpoint)."""

    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)

    @field_validator("content")
    @classmethod
    def _strip_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content must not be empty")
        return value
