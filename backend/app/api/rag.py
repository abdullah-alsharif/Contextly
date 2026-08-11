"""RAG debug router: POST /api/v1/rag/query (dev-only; docs/roadmap.md Phase 6).

Registered in `create_app` only when APP_ENV=dev (research.md R7) — in any
other environment the route does not exist and requests get the standard 404.
Every endpoint is guarded by the router-level get_current_user dependency, so
unauthenticated requests get 401 by construction (contracts/auth.md §1).
Error mapping: 404 conversation not found/not owned/deleted (docs/security.md
§2 anti-enumeration), 422 body validation (docs/api.md §6), 502 question
embedding failure after retries (docs/rag.md §7).
"""

from __future__ import annotations

import logging
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import enforce_general_rate_limit
from app.core.config import Settings, get_settings
from app.core.security.deps import get_current_user
from app.core.security.identity import Identity
from app.db.session import get_db
from app.providers.ai.base import AIProvider
from app.schemas.retrieval import RagQueryIn, RagQueryOut, RetrievalHitOut
from app.services.retrieval import (
    ConversationNotFoundError,
    QuestionEmbeddingError,
    search_ready_documents,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/rag",
    tags=["rag"],
    dependencies=[Depends(get_current_user), Depends(enforce_general_rate_limit)],
)


def get_ai_provider(request: Request) -> AIProvider:
    """The app-scoped AI provider (injectable in tests via create_app)."""
    provider: AIProvider = request.app.state.ai_provider
    return provider


@router.post("/query", response_model=RagQueryOut)
async def query_rag(
    body: RagQueryIn,
    identity: Identity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    ai: AIProvider = Depends(get_ai_provider),
) -> RagQueryOut:
    """Return the top-K most relevant chunks for a question, scoped to a conversation.

    Debug-only surface: exposes chunk content so retrieval quality can be
    inspected (spec US4); the Phase 7 message path will use the leaner sources
    shape (docs/rag.md §5).
    """
    if len(body.question) > settings.rag_query_max_chars:
        raise HTTPException(
            status_code=422,
            detail=(
                f"question must be at most {settings.rag_query_max_chars} characters"
            ),
        )
    started = perf_counter()
    try:
        hits = await search_ready_documents(
            db,
            ai,
            settings,
            identity=identity,
            conversation_id=body.conversation_id,
            question=body.question,
            top_k=body.top_k,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except QuestionEmbeddingError as exc:
        logger.error("question embedding failed for user %s: %s", identity.user_id, exc)
        raise HTTPException(
            status_code=502, detail="question embedding is unavailable"
        ) from exc

    return RagQueryOut(
        question=body.question,
        conversation_id=body.conversation_id,
        hits=[
            RetrievalHitOut(
                document_id=hit.document_id,
                filename=hit.filename,
                page_number=hit.page_number,
                chunk_index=hit.chunk_index,
                similarity=hit.similarity,
                content=hit.content,
            )
            for hit in hits
        ],
        retrieval_ms=(perf_counter() - started) * 1000,
    )
