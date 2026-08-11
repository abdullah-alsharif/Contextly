"""Messages router: message history + streaming send (docs/api.md §4).

Every endpoint is guarded by the router-level get_current_user dependency, so
unauthenticated requests get 401 by construction (contracts/auth.md §1). Both
the send and history paths carry the per-user chat rate limit (docs/security.md
§5, contracts/chat.md §4).

Error mapping (contracts/chat.md §4): 404 unowned/missing/deleted conversation,
400 conversation with no selected documents (docs/chat.md §6), 409 idempotency
key still in flight, 422 question over the documented 4000-char cap or an
out-of-bounds `limit`, 502 question embedding failure (docs/rag.md §7),
429 rate limited.

Send flow (docs/chat.md §4): `prepare_chat` commits the user message on its own
session BEFORE the response starts, so every HTTP error surfaces as a clean
status and a client disconnect mid-stream never loses the exchange
(contracts/chat.md §3). Once streaming begins, the SSE protocol is
meta/delta*/done, or error (terminal) on provider failure; `stream_chat_events`
commits the assistant message on its own session at stream end.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dependencies import (
    InFlightRegistry,
    enforce_chat_rate_limit,
    get_in_flight_registry,
)
from app.core.config import Settings, get_settings
from app.core.security.deps import get_current_user
from app.core.security.identity import Identity
from app.db.session import get_db
from app.providers.ai.base import AIProvider
from app.schemas.message import MessageOut, MessageSendIn
from app.services.conversations import ConversationNotFoundError
from app.services.retrieval import QuestionEmbeddingError
from app.services.chat import (
    IdempotencyInFlightError,
    NoDocumentsSelectedError,
    PreparedChat,
    list_messages,
    prepare_chat,
    stream_chat_events,
)

logger = logging.getLogger(__name__)

_DEFAULT_PAGE_SIZE = get_settings().history_page_size

router = APIRouter(
    prefix="/conversations",
    tags=["chat"],
    dependencies=[Depends(get_current_user)],
)


def get_ai_provider(request: Request) -> AIProvider:
    """The app-scoped AI provider (injectable in tests via create_app)."""
    provider: AIProvider = request.app.state.ai_provider
    return provider


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    """The app-scoped session factory (injectable in tests via create_app)."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return factory


def _format_sse(event: str, data: dict[str, Any]) -> str:
    """One SSE block: `event: <name>` + `data: <json>` (docs/api.md §4)."""
    payload = json.dumps(data, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


@router.get(
    "/{conversation_id}/messages",
    response_model=list[MessageOut],
    dependencies=[Depends(enforce_chat_rate_limit)],
)
async def get_history(
    conversation_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=100)] = _DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
    identity: Identity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    response: Response = None,  # type: ignore[assignment]  # FastAPI requires bare Response
) -> list[dict[str, Any]]:
    """History for one conversation, oldest first (docs/api.md §4).

    Keyset pagination: `?limit&cursor=`; the opaque next cursor is returned in
    the `X-Next-Cursor` header when more pages exist. `limit` is honored up to
    the documented max of 100 (default `history_page_size` = 50,
    contracts/chat.md §2, §5); a stale cursor yields the remaining page,
    never an error (contracts/chat.md §2).
    """
    try:
        rows, next_cursor = await list_messages(
            db,
            identity,
            conversation_id,
            page_size=limit,
            cursor=cursor,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if response is not None and next_cursor is not None:
        response.headers["X-Next-Cursor"] = next_cursor
    return rows


@router.post(
    "/{conversation_id}/messages",
    dependencies=[Depends(enforce_chat_rate_limit)],
)
async def send_message(
    conversation_id: uuid.UUID,
    body: MessageSendIn,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    identity: Identity = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    ai: AIProvider = Depends(get_ai_provider),
    in_flight: InFlightRegistry = Depends(get_in_flight_registry),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> StreamingResponse:
    """Send a question → SSE stream of the answer (docs/api.md §4).

    The client may retry safely with the same `Idempotency-Key`: a completed
    previous answer is replayed with the original ids + stored sources, a key
    whose exchange is still streaming gets 409, and a dead duplicate reruns the
    pipeline on the same user message id (contracts/chat.md §3).
    """
    question = body.content
    if len(question) > settings.chat_question_max_chars:
        raise HTTPException(
            status_code=422,
            detail=(
                "question must be at most "
                f"{settings.chat_question_max_chars} characters"
            ),
        )

    key = (idempotency_key or "").strip() or None

    try:
        prepared = await prepare_chat(
            session_factory,
            ai,
            settings,
            identity=identity,
            conversation_id=conversation_id,
            question=question,
            idempotency_key=key,
            in_flight=in_flight,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NoDocumentsSelectedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IdempotencyInFlightError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except QuestionEmbeddingError as exc:
        logger.error("question embedding failed for user %s: %s", identity.user_id, exc)
        raise HTTPException(
            status_code=502, detail="question embedding is unavailable"
        ) from exc

    if key is not None and not in_flight.mark(str(conversation_id), key):
        raise HTTPException(
            status_code=409, detail="this idempotency key is still streaming"
        )

    try:
        return StreamingResponse(
            _event_stream(ai, settings, prepared, in_flight, session_factory),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception:
        if key is not None:
            in_flight.clear(str(conversation_id), key)
        raise


async def _event_stream(
    ai: AIProvider,
    settings: Settings,
    prepared: PreparedChat,
    in_flight: InFlightRegistry,
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[str]:
    """Wrap session events into SSE frames; release the key on stream end."""
    async for chat_event in stream_chat_events(
        session_factory,
        ai,
        prepared=prepared,
        settings=settings,
        in_flight=in_flight,
    ):
        yield _format_sse(chat_event.event, chat_event.data)
