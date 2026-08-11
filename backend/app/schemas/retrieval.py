"""Pydantic schemas for the Phase 6 retrieval debug endpoint.

Contract: specs/007-rag-retrieval-engine/contracts/retrieval.md §2, following
docs/api.md §2/§6 (422 on validation, stable error shape) and docs/security.md
§4 (question length cap). The debug endpoint exposes chunk content for quality
inspection; the Phase 7 message surface will use the leaner sources shape
(docs/rag.md §5).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator

DEFAULT_TOP_K_MAX = 50


class RagQueryIn(BaseModel):
    """Question + conversation scope for a retrieval query.

    The question length cap is enforced against the live setting
    (``settings.rag_query_max_chars``, contracts/retrieval.md §4) at the endpoint
    layer — this schema only applies a generous structural bound so request bodies
    stay bounded even if an operator raises the cap (docs/security.md §4).
    """

    question: str = Field(min_length=1, max_length=10000)
    conversation_id: uuid.UUID
    top_k: int | None = Field(default=None, ge=1, le=DEFAULT_TOP_K_MAX)

    @field_validator("question")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be empty")
        return value


class RetrievalHitOut(BaseModel):
    """One ranked chunk with source metadata (docs/rag.md §5)."""

    document_id: uuid.UUID
    filename: str
    page_number: int | None
    chunk_index: int
    similarity: float
    content: str


class RagQueryOut(BaseModel):
    """Debug endpoint response: the ranked hits plus timing."""

    question: str
    conversation_id: uuid.UUID
    hits: list[RetrievalHitOut]
    retrieval_ms: float
