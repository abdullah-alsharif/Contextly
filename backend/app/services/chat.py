"""Chat service: message history + the send → retrieve → generate pipeline.

Contract: specs/008-chat-conversations/contracts/chat.md §2-3, following
docs/chat.md §4-6, docs/api.md §4 (SSE protocol, idempotency), docs/rag.md
§4-5/§7, and docs/security.md §4 (prompt-injection mitigation).

Pipeline (docs/chat.md §4), split in two phases so HTTP errors surface before
the SSE stream starts:

1. `prepare_chat` — on its OWN session: validate ownership, check the document
   selection, persist the user message (idempotency-deduped), embed the
   question, retrieve top-K hits, then COMMIT — a client disconnect mid-stream
   never loses the exchange (contracts/chat.md §3).
2. `stream_chat_events` — build the untrusted-excerpt prompt, generate
   (streaming when supported), then persist the assistant message on a
   short-lived session opened only at stream end: the LLM stream must never
   hold a pooled DB connection, or a few concurrent chats exhaust the pool
   (docs/chat.md §4). Each phase re-applies the RLS role + claim
   (docs/multi-tenancy.md §2). A mid-stream provider failure persists the
   partial answer with status='error' so the UI can offer a retry
   (docs/chat.md §6, docs/rag.md §7).
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from logging import getLogger
from time import perf_counter
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security.deps import apply_identity_to_session
from app.core.security.identity import Identity
from app.providers.ai.base import AIProvider, AIProviderError, estimate_tokens
from app.services.chat_context import (
    HistoryWindow,
    REWRITE_MARKER_OK,
    build_prompt_messages,
    fetch_history_window,
    rewrite_question,
)
from app.services.conversations import (
    DEFAULT_TITLE,
    get_conversation,
    touch_conversation,
)
from app.services.retrieval import (
    RetrievalHit,
    search_ready_documents,
)

logger = getLogger(__name__)

_NO_RELEVANT_ANSWER = (
    "No relevant documents found in this conversation. "
    "Try adding more documents or rephrasing your question."
)

# Re-exports keep the pre-existing test matrix importable unchanged.
from app.services.chat_context import (  # noqa: E402  (module-level re-export)
    _QUESTION_CLOSE,  # noqa: F401  (re-export for tests)
    _QUESTION_OPEN,  # noqa: F401  (re-export for tests)
    _SYSTEM_PROMPT,  # noqa: F401  (re-export for tests)
    sanitize_question,  # noqa: F401  (re-export for tests)
)

_build_prompt_messages = build_prompt_messages  # backward-compatible alias

_SELECTED_DOC_COUNT = text(
    """
    select count(*) from conversation_documents
    where conversation_id = :conversation_id
    """
)

_INSERT_USER_MESSAGE = text(
    """
    insert into messages (conversation_id, role, content, idempotency_key)
    values (:conversation_id, 'user', :content, :idempotency_key)
    on conflict (conversation_id, idempotency_key)
      where idempotency_key is not null
    do nothing
    returning id
    """
)

_FIND_USER_MESSAGE_BY_KEY = text(
    """
    select id from messages
    where conversation_id = :conversation_id
      and idempotency_key = :idempotency_key
      and role = 'user'
    """
)

_FIND_ASSISTANT_AFTER = text(
    """
    select m2.id, m2.content, m2.status, m2.sources
    from messages m2
    where m2.conversation_id = :conversation_id
      and m2.role = 'assistant'
      and m2.created_at > (
          select created_at from messages where id = :user_message_id
      )
    order by m2.created_at desc
    limit 1
    """
)

_INSERT_ASSISTANT_MESSAGE = text(
    """
    insert into messages (
        conversation_id, role, content, sources, status,
        input_tokens, output_tokens, retrieval_ms, llm_ms
    )
    values (
        :conversation_id, 'assistant', :content, :sources, :status,
        :input_tokens, :output_tokens, :retrieval_ms, :llm_ms
    )
    returning id, created_at
    """
)

_HISTORY = text(
    """
    select id, role, content, sources, status,
           input_tokens, output_tokens, retrieval_ms, llm_ms, created_at
    from messages
    where conversation_id = :conversation_id
      and (cast(:cursor_created as timestamptz) is null
           or (created_at, id) < (
               cast(:cursor_created as timestamptz), cast(:cursor_id as uuid)
           ))
    order by created_at desc, id desc
    limit :page_size
    """
)


@dataclass(frozen=True)
class ChatEvent:
    """One SSE event: meta / delta / done / error (docs/api.md §4)."""

    event: str
    data: dict[str, Any]


@dataclass
class PreparedChat:
    """Everything needed to stream one answer (user message committed).

    `replay` is set on an idempotent retry whose previous answer completed:
    the client gets the stored text back (contracts/chat.md §3).

    Multi-turn artifacts (specs/014-chat-multi-turn-context, data-model.md):
    `rewritten_query`/`rewrite_marker` describe the derived retrieval query and
    `context_window` is the bounded generation window — all per-request,
    never persisted (FR-002).
    """

    conversation_id: uuid.UUID
    user_message_id: uuid.UUID
    user_id: uuid.UUID
    question: str
    conversation_title: str
    retrieval_ms: float
    idempotency_key: str | None = None
    hits: list[RetrievalHit] = field(default_factory=list)
    replay: tuple[uuid.UUID, str, list[dict[str, Any]]] | None = None
    rewritten_query: str | None = None
    rewrite_marker: str | None = None
    context_window: HistoryWindow | None = None


class NoDocumentsSelectedError(Exception):
    """Conversation has no selected documents (→ 400, docs/chat.md §6)."""


class IdempotencyInFlightError(Exception):
    """The idempotency key's original exchange is still streaming (→ 409)."""


async def _check_selection(db: AsyncSession, conversation_id: uuid.UUID) -> None:
    result = await db.execute(
        _SELECTED_DOC_COUNT, {"conversation_id": str(conversation_id)}
    )
    if result.scalar_one() == 0:
        raise NoDocumentsSelectedError("Add documents to this conversation first.")


async def prepare_chat(
    session_factory: async_sessionmaker[AsyncSession],
    ai: AIProvider,
    settings: Settings,
    *,
    identity: Identity,
    conversation_id: uuid.UUID,
    question: str,
    idempotency_key: str | None,
    in_flight: Any = None,
) -> PreparedChat:
    """Validate + persist the user message + retrieve hits (raises HTTP-able errors).

    Commits the user message on its own session before the stream starts
    (contracts/chat.md §3) — a disconnect mid-stream never loses the exchange.
    A duplicate key whose original exchange is still streaming raises
    IdempotencyInFlightError (409); a dead duplicate reruns the pipeline on
    the same user message.
    """
    async with session_factory() as db:
        await apply_identity_to_session(db, identity)
        conversation = await get_conversation(db, identity, conversation_id)
        await _check_selection(db, conversation_id)

        user_message_id, existed = await _persist_user_message(
            db, conversation_id, question, idempotency_key
        )

        if idempotency_key is not None and existed:
            # Duplicate key: replay a completed exchange, 409 an in-flight one,
            # or rerun the pipeline for a dead one (failed before any output).
            replay = await _find_completed_replay(db, conversation_id, user_message_id)
            if replay is not None:
                return PreparedChat(
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    user_id=identity.user_id,
                    question=question,
                    conversation_title=conversation["title"],
                    retrieval_ms=0.0,
                    idempotency_key=idempotency_key,
                    hits=[],
                    replay=replay,
                )
            if in_flight is not None:
                if not in_flight.mark(str(conversation_id), idempotency_key):
                    raise IdempotencyInFlightError(
                        "this idempotency key is still streaming; retry shortly"
                    )
                # Probe only — the router owns marking for the real stream.
                in_flight.clear(str(conversation_id), idempotency_key)

        started = perf_counter()
        # Multi-turn context (specs/014-chat-multi-turn-context): derive the
        # retrieval query from prior messages and fetch the generation window.
        prior_history = await fetch_history_window(
            db,
            conversation_id,
            max_messages=settings.chat_rewrite_max_messages,
            max_tokens=settings.chat_rewrite_max_tokens,
            exclude_message_id=user_message_id,
        )
        rewritten_query: str | None = None
        rewrite_marker: str | None = None
        if prior_history.messages:
            derived_query, rewrite_marker = await rewrite_question(
                ai,
                question,
                prior_history,
                enabled=settings.chat_rewrite_enabled,
            )
            rewritten_query = (
                derived_query if rewrite_marker == REWRITE_MARKER_OK else None
            )
        else:
            derived_query = question
        context_window = await fetch_history_window(
            db,
            conversation_id,
            max_messages=settings.chat_context_max_messages,
            max_tokens=settings.chat_context_max_tokens,
            exclude_message_id=user_message_id,
        )
        hits = await search_ready_documents(
            db,
            ai,
            settings,
            identity=identity,
            conversation_id=conversation_id,
            question=derived_query,
        )
        retrieval_ms = (perf_counter() - started) * 1000

        prepared = PreparedChat(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            user_id=identity.user_id,
            question=question,
            conversation_title=conversation["title"],
            retrieval_ms=retrieval_ms,
            idempotency_key=idempotency_key,
            hits=hits,
            rewritten_query=rewritten_query,
            rewrite_marker=rewrite_marker,
            context_window=context_window,
        )
        await db.commit()

        window_messages = (
            len(context_window.messages) if context_window.messages else 0
        )
        window_tokens = context_window.total_tokens if context_window.messages else 0
        logger.info(
            "chat multi-turn | user=%s | conversation=%s | rewrite=%s | "
            "rewritten_query=%s | window_messages=%d | window_tokens=%d",
            identity.user_id,
            conversation_id,
            rewrite_marker or "n/a",
            rewritten_query or "",
            window_messages,
            window_tokens,
        )
        return prepared


async def _persist_user_message(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    question: str,
    idempotency_key: str | None,
) -> tuple[uuid.UUID, bool]:
    """Insert the user message; on key reuse return (existing id, existed=True)."""
    result = await db.execute(
        _INSERT_USER_MESSAGE,
        {
            "conversation_id": str(conversation_id),
            "content": question,
            "idempotency_key": idempotency_key,
        },
    )
    row = result.one_or_none()
    if row is not None:
        return (row.id, False)

    result = await db.execute(
        _FIND_USER_MESSAGE_BY_KEY,
        {
            "conversation_id": str(conversation_id),
            "idempotency_key": idempotency_key,
        },
    )
    existing = result.one()
    return (existing.id, True)


async def _find_completed_replay(
    db: AsyncSession, conversation_id: uuid.UUID, user_message_id: uuid.UUID
) -> tuple[uuid.UUID, str, list[dict[str, Any]]] | None:
    """The NEWEST completed (status='done') assistant answer after the user message, if any.

    An old `status='error'` partial from a failed attempt must never shadow a
    later `done` answer, or replays would re-run the pipeline and stack
    duplicates (spec US4/AC1, FR-014).
    """
    result = await db.execute(
        _FIND_ASSISTANT_AFTER,
        {
            "conversation_id": str(conversation_id),
            "user_message_id": str(user_message_id),
        },
    )
    row = result.one_or_none()
    if row is None or row.status != "done":
        return None
    return (row.id, row.content, _parse_sources(row.sources))


async def stream_chat_events(
    session_factory: async_sessionmaker[AsyncSession],
    ai: AIProvider,
    *,
    prepared: PreparedChat,
    settings: Settings,
    in_flight: Any = None,
) -> Any:
    """Yield SSE events for one answer; persist the assistant message once.

    Persistence runs on a short-lived session opened only at stream end
    (docs/chat.md §4) — the provider stream never holds a pooled connection.
    A mid-stream provider failure persists the partial text with
    status='error' and yields a terminal error event (docs/chat.md §6,
    docs/rag.md §7); an unexpected non-provider failure yields a terminal
    error event and persists nothing. The idempotency key is released when
    the stream ends.
    """
    yield ChatEvent("meta", {"message_id": str(prepared.user_message_id)})

    try:
        if prepared.replay is not None:
            # Replay: the stored answer needs no session.
            assistant_id, content, sources = prepared.replay
            yield ChatEvent("delta", {"text": content})
            yield ChatEvent(
                "done",
                {"id": str(assistant_id), "sources": sources, "llm_ms": 0},
            )
            return

        if not prepared.hits:
            # docs/rag.md §7: no qualifying chunks -> skip the LLM.
            assistant_id = await _persist_answer_on_own_session(
                session_factory,
                prepared,
                settings=settings,
                content=_NO_RELEVANT_ANSWER,
                sources=[],
                status="done",
                input_tokens=0,
                output_tokens=estimate_tokens(_NO_RELEVANT_ANSWER),
                retrieval_ms=prepared.retrieval_ms,
                llm_ms=0.0,
            )
            yield ChatEvent("delta", {"text": _NO_RELEVANT_ANSWER})
            yield ChatEvent(
                "done",
                {"id": str(assistant_id), "sources": [], "llm_ms": 0},
            )
            return

        prompt = build_prompt_messages(
            prepared.question,
            prepared.hits,
            history=prepared.context_window,
        )
        input_tokens = estimate_tokens(
            prompt[0]["content"] + "\n" + prompt[1]["content"]
        )

        started = perf_counter()
        sources = _sources_from_hits(prepared.hits)
        try:
            stream = await ai.generate(prompt, stream=ai.supports_streaming)
        except AIProviderError as exc:
            logger.error(
                "chat generation failed for user %s: %s",
                prepared.conversation_id,
                exc,
            )
            yield ChatEvent(
                "error", {"message": "the AI provider failed; try again"}
            )
            return

        partial: list[str] = []

        # Inject a [1] citation marker for dev/CI (FakeProvider has none).
        def _annotate_answer(text: str) -> str:
            if not sources:
                return text
            if "[" in text and "]" in text:
                return text
            return f"{text}\n\n[1]"

        if ai.supports_streaming:
            if not isinstance(stream, AsyncIterator):
                raise AIProviderError(
                    "provider did not return a stream while streaming is enabled",
                    provider="unknown",
                )
            try:
                async for delta in stream:
                    partial.append(delta)
                    yield ChatEvent("delta", {"text": delta})
            except AIProviderError as exc:
                logger.error(
                    "chat stream failed for user %s: %s",
                    prepared.conversation_id,
                    exc,
                )
                content = "".join(partial)
                if content:
                    # Persist the partial so the UI can offer a retry
                    # (docs/chat.md §6, docs/rag.md §7).
                    await _persist_answer_on_own_session(
                        session_factory,
                        prepared,
                        settings=settings,
                        content=content,
                        sources=sources,
                        status="error",
                        input_tokens=input_tokens,
                        output_tokens=estimate_tokens(content),
                        retrieval_ms=prepared.retrieval_ms,
                        llm_ms=(perf_counter() - started) * 1000,
                    )
                yield ChatEvent(
                    "error",
                    {"message": "the AI provider failed mid-stream; retry"},
                )
                return
            content = "".join(partial)
            annotated = _annotate_answer(content)
            if annotated != content:
                content = annotated
                yield ChatEvent("delta", {"text": annotated[len("".join(partial)):]})
            llm_ms = (perf_counter() - started) * 1000
        else:
            if not isinstance(stream, str):
                raise AIProviderError(
                    "non-streaming provider returned a stream result",
                    provider="unknown",
                )
            content = _annotate_answer(stream)
            llm_ms = (perf_counter() - started) * 1000
            yield ChatEvent("delta", {"text": content})

        assistant_id = await _persist_answer_on_own_session(
            session_factory,
            prepared,
            settings=settings,
            content=content,
            sources=sources,
            status="done",
            input_tokens=input_tokens,
            output_tokens=estimate_tokens(content),
            retrieval_ms=prepared.retrieval_ms,
            llm_ms=llm_ms,
        )
        yield ChatEvent(
            "done",
            {
                "id": str(assistant_id),
                "sources": sources,
                "llm_ms": round(llm_ms),
            },
        )
    except Exception as exc:
        # Non-provider failure: terminate; nothing was persisted (docs/chat.md §6).
        logger.exception(
            "chat stream failed unexpectedly for conversation %s: %s",
            prepared.conversation_id,
            exc,
        )
        yield ChatEvent(
            "error", {"message": "internal error; the answer was not saved"}
        )
    finally:
        if in_flight is not None and prepared.idempotency_key is not None:
            in_flight.clear(str(prepared.conversation_id), prepared.idempotency_key)


async def _persist_answer_on_own_session(
    session_factory: async_sessionmaker[AsyncSession],
    prepared: PreparedChat,
    *,
    settings: Settings,
    content: str,
    sources: list[dict[str, Any]],
    status: str,
    input_tokens: int,
    output_tokens: int,
    retrieval_ms: float,
    llm_ms: float,
) -> uuid.UUID:
    """Persist the assistant message on a short-lived session (RLS-scoped).

    Opens its own session so `stream_chat_events` never holds a pooled
    connection while the provider is generating (docs/chat.md §4). For
    completed answers (status='done') also auto-renames the default title and
    touches the conversation; a mid-stream failure only persists the partial
    row (status='error').
    """
    async with session_factory() as db:
        await apply_identity_to_session(db, Identity(user_id=prepared.user_id))
        assistant_id = await _persist_answer(
            db,
            prepared,
            content=content,
            sources=sources,
            status=status,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            retrieval_ms=retrieval_ms,
            llm_ms=llm_ms,
        )
        if status == "done":
            await _maybe_auto_rename(db, prepared, settings)
            await touch_conversation(
                db,
                Identity(user_id=prepared.user_id),
                prepared.conversation_id,
            )
        await db.commit()
        return assistant_id


async def _persist_answer(
    db: AsyncSession,
    prepared: PreparedChat,
    *,
    content: str,
    sources: list[dict[str, Any]],
    status: str,
    input_tokens: int,
    output_tokens: int,
    retrieval_ms: float,
    llm_ms: float,
) -> uuid.UUID:
    """Insert the assistant message; returns its id."""
    result = await db.execute(
        _INSERT_ASSISTANT_MESSAGE,
        {
            "conversation_id": str(prepared.conversation_id),
            "content": content,
            "sources": json.dumps(sources),
            "status": status,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "retrieval_ms": round(retrieval_ms),
            "llm_ms": round(llm_ms),
        },
    )
    return cast(uuid.UUID, result.one().id)


async def _maybe_auto_rename(
    db: AsyncSession, prepared: PreparedChat, settings: Settings
) -> None:
    """Rename the default title to the first question (docs/chat.md §6)."""
    if prepared.conversation_title != DEFAULT_TITLE:
        return
    title = prepared.question.strip()[: settings.auto_rename_title_max_chars]
    await db.execute(
        text(
            "update conversations set title = :title, updated_at = now() "
            "where id = :conversation_id and title = :default_title"
        ),
        {
            "title": title,
            "conversation_id": str(prepared.conversation_id),
            "default_title": DEFAULT_TITLE,
        },
    )


def _sources_from_hits(hits: list[RetrievalHit]) -> list[dict[str, Any]]:
    """Roll retrieval hits into the persisted sources snapshot (docs/rag.md §5).

    Includes ``excerpt`` (trimmed chunk text) so the frontend source viewer can
    render the highlighted excerpt straight from the stored payload — spec
    009-frontend-buildout FR-011 ("no extra query"). Limited to 600 chars to
    keep message rows small.
    """
    return [
        {
            "document_id": str(hit.document_id),
            "filename": hit.filename,
            "page_number": hit.page_number,
            "chunk_index": hit.chunk_index,
            "similarity": round(hit.similarity, 4),
            "excerpt": hit.content[:600],
        }
        for hit in hits
    ]


async def list_messages(
    db: AsyncSession,
    identity: Identity,
    conversation_id: uuid.UUID,
    *,
    page_size: int,
    cursor: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """History for one conversation, oldest first (docs/api.md §4).

    Keyset pagination on `(created_at, id)` (contracts/chat.md §2): pages are
    fetched newest-first so the most recent messages always arrive in the
    first page, then reversed for the documented oldest-first order. The
    opaque cursor encodes `created_at|id` of the oldest returned message;
    a stale or unparseable cursor simply yields the remaining page — never an
    error (contracts/chat.md §2).
    """
    await get_conversation(db, identity, conversation_id)

    cursor_created: str | None = None
    cursor_id: str | None = None
    if cursor:
        decoded = _decode_cursor(cursor)
        if decoded is not None:
            cursor_created, cursor_id = decoded

    result = await db.execute(
        _HISTORY,
        {
            "conversation_id": str(conversation_id),
            "cursor_created": (
                datetime.fromisoformat(cursor_created) if cursor_created else None
            ),
            "cursor_id": cursor_id,
            "page_size": page_size + 1,
        },
    )
    raw = result.all()
    has_more = len(raw) > page_size
    page = list(raw[:page_size])
    page.reverse()  # oldest first

    rows = [
        {
            "id": row.id,
            "role": row.role,
            "content": row.content,
            "sources": _parse_sources(row.sources),
            "status": row.status,
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "retrieval_ms": row.retrieval_ms,
            "llm_ms": row.llm_ms,
            "created_at": row.created_at,
        }
        for row in page
    ]
    # The next page continues strictly OLDER than the oldest message of this
    # page (page[0] after reversal) — using the newest would re-emit rows that
    # already appeared at the end of this page.
    next_cursor = None
    if has_more:
        oldest = page[0]
        next_cursor = _encode_cursor(oldest.created_at, oldest.id)
    return rows, next_cursor


def _encode_cursor(created_at: datetime, message_id: uuid.UUID) -> str:
    """Opaque base64url cursor: `{iso}|{id}` (contracts/chat.md §2)."""
    raw = f"{created_at.isoformat()}|{message_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str] | None:
    """Parse an opaque cursor; anything malformed → None (never an error)."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        created_at, message_id = raw.split("|", 1)
        datetime.fromisoformat(created_at)  # validate before use
        uuid.UUID(message_id)
        return (created_at, message_id)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return None


def _parse_sources(value: Any) -> list[dict[str, Any]]:
    """asyncpg returns jsonb as str for text() queries; normalize to a list."""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            return cast(list[dict[str, Any]], json.loads(value))
        except json.JSONDecodeError:  # pragma: no cover - corrupt legacy row
            return []
    return cast(list[dict[str, Any]], value)
