"""Conversation management: CRUD + explicit document allow-list (Phase 7).

Contract: specs/008-chat-conversations/contracts/chat.md §1, following
docs/api.md §3 (conversations API), docs/chat.md §2 (selection semantics:
only the caller's own `ready` documents, immediate effect, no re-processing),
and docs/security.md §2 (ownership failures → 404, never 403). Raw
parameterized SQL on the caller's RLS-scoped session (project pattern —
mirrors services/documents.py); the database stays the enforced boundary
(docs/multi-tenancy.md §2).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.identity import Identity

DEFAULT_TITLE = "New conversation"

_SELECT_CONVERSATION = text(
    """
    select id, title, pinned, archived_at, created_at, updated_at,
           (select count(*)::int from messages m where m.conversation_id = conversations.id) as message_count
    from conversations
    where id = :conversation_id and user_id = :user_id and deleted_at is null
    """
)

_SELECT_CONVERSATIONS = text(
    """
    select id, title, pinned, archived_at, created_at, updated_at,
           (select count(*)::int from messages m where m.conversation_id = conversations.id) as message_count
    from conversations
    where user_id = :user_id and deleted_at is null and archived_at is null
    order by pinned desc, updated_at desc
    """
)

_SELECT_ARCHIVED_CONVERSATIONS = text(
    """
    select id, title, pinned, archived_at, created_at, updated_at,
           (select count(*)::int from messages m where m.conversation_id = conversations.id) as message_count
    from conversations
    where user_id = :user_id and deleted_at is null and archived_at is not null
    order by updated_at desc
    """
)

# Search (sidebar "Search chats", docs/api.md §3): case-insensitive title +
# message-content match, archived included, ranked. strpos/lower (not ILIKE)
# so input can't inject wildcards; tsvector can't express infix matches.
_SEARCH_CONVERSATIONS = text(
    """
    with matching as (
        select c.id, c.title, c.pinned, c.archived_at, c.created_at, c.updated_at,
               case
                   when lower(c.title) = lower(:q) then 0
                   when strpos(lower(c.title), lower(:q)) > 0 then 1
                   else 2
               end as title_rank
        from conversations c
        where c.user_id = :user_id and c.deleted_at is null
          and (
              strpos(lower(c.title), lower(:q)) > 0
              or exists (
                  select 1 from messages m
                  where m.conversation_id = c.id
                    and strpos(lower(m.content), lower(:q)) > 0
              )
          )
    )
    select m.id, m.title, m.pinned, m.archived_at, m.created_at, m.updated_at,
           m.title_rank,
           (select count(*)::int from messages mc where mc.conversation_id = m.id) as message_count,
           (
               select msg.content
               from messages msg
               where msg.conversation_id = m.id
                 and strpos(lower(msg.content), lower(:q)) > 0
               order by msg.created_at desc
               limit 1
           ) as matched_content
    from matching m
    order by m.title_rank asc, m.updated_at desc, m.id asc
    limit :limit offset :offset
    """
)

SEARCH_LIMIT = 50
SEARCH_PREVIEW_CHARS = 160

_SELECT_SELECTED_DOCUMENTS = text(
    """
    select d.id, d.filename, d.status, d.file_size_bytes, d.total_chunks,
           d.status_error, d.created_at, d.updated_at
    from conversation_documents cd
    join documents d on d.id = cd.document_id
    where cd.conversation_id = :conversation_id
    order by d.created_at asc
    """
)

_SELECT_READY_DOCUMENT = text(
    """
    select 1 from documents
    where id = :document_id and user_id = :user_id
      and status = 'ready' and deleted_at is null
    """
)

_INSERT_CONVERSATION = text(
    """
    insert into conversations (user_id, title)
    values (:user_id, :title)
    returning id, title, pinned, archived_at, created_at, updated_at,
              (select count(*)::int from messages m where m.conversation_id = conversations.id) as message_count
    """
)

_UPDATE_CONVERSATION = text(
    """
    update conversations
    set title       = coalesce(cast(:title as text), title),
        pinned      = coalesce(cast(:pinned as boolean), pinned),
        archived_at = case
            when cast(:archived as boolean) is null then archived_at
            when cast(:archived as boolean) then now()
            else null end,
        updated_at  = now()
    where id = :conversation_id and user_id = :user_id and deleted_at is null
    returning id, title, pinned, archived_at, created_at, updated_at,
              (select count(*)::int from messages m where m.conversation_id = conversations.id) as message_count
    """
)

_DELETE_CONVERSATION = text(
    """
    update conversations
    set deleted_at = now(), updated_at = now()
    where id = :conversation_id and user_id = :user_id and deleted_at is null
    """
)

_INSERT_SELECTION = text(
    """
    insert into conversation_documents (conversation_id, document_id)
    values (:conversation_id, :document_id)
    """
)

_CLEAR_SELECTION = text(
    """
    delete from conversation_documents where conversation_id = :conversation_id
    """
)

_TOUCH_CONVERSATION = text(
    """
    update conversations set updated_at = now()
    where id = :conversation_id and user_id = :user_id and deleted_at is null
    """
)


class ConversationNotFoundError(Exception):
    """Conversation missing, not owned, or deleted (→ 404, deliberately ambiguous)."""


class DocumentSelectionError(Exception):
    """A selected document is not owned by the caller or not ready (→ 404)."""


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "pinned": row.pinned,
        "archived": row.archived_at is not None,
        "message_count": row.message_count,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def _require_ready_documents(
    db: AsyncSession, identity: Identity, document_ids: list[uuid.UUID]
) -> None:
    """Every id must be the caller's own, `ready`, undeleted document (docs/chat.md §2)."""
    for document_id in document_ids:
        result = await db.execute(
            _SELECT_READY_DOCUMENT,
            {
                "document_id": str(document_id),
                "user_id": str(identity.user_id),
            },
        )
        if result.one_or_none() is None:
            raise DocumentSelectionError(
                "document is not yours, not ready, or does not exist"
            )


async def create_conversation(
    db: AsyncSession,
    identity: Identity,
    *,
    title: str | None,
    document_ids: list[uuid.UUID] | None,
) -> dict[str, Any]:
    """Create a conversation with an optional validated document selection."""
    selected = document_ids or []
    if selected:
        await _require_ready_documents(db, identity, selected)

    result = await db.execute(
        _INSERT_CONVERSATION,
        {
            "user_id": str(identity.user_id),
            "title": title or DEFAULT_TITLE,
        },
    )
    row = result.one()
    conversation = _row_to_dict(row)

    for document_id in selected:
        await db.execute(
            _INSERT_SELECTION,
            {"conversation_id": conversation["id"], "document_id": str(document_id)},
        )
    return conversation


async def list_conversations(
    db: AsyncSession, identity: Identity, *, archived: bool = False
) -> list[dict[str, Any]]:
    """The caller's conversations: pinned first then newest (docs/api.md §3).

    Archived conversations are excluded unless `archived` is true, which
    returns only archived ones (docs/chat.md §7).
    """
    query = _SELECT_ARCHIVED_CONVERSATIONS if archived else _SELECT_CONVERSATIONS
    result = await db.execute(query, {"user_id": str(identity.user_id)})
    return [_row_to_dict(row) for row in result.all()]


def _match_snippet(content: str, query: str, max_chars: int = SEARCH_PREVIEW_CHARS) -> str:
    """Preview window around the first case-insensitive match, ellipsized."""
    content = " ".join(content.split())
    if len(content) <= max_chars:
        return content
    index = content.casefold().find(query.casefold())
    if index < 0:
        return f"{content[:max_chars]}…"
    start = max(index - max_chars // 3, 0)
    end = min(start + max_chars, len(content))
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content) else ""
    return f"{prefix}{content[start:end]}{suffix}"


async def search_conversations(
    db: AsyncSession,
    identity: Identity,
    *,
    query: str,
    limit: int = SEARCH_LIMIT,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Search the caller's conversations — title and message content — with a
    stable ranking (docs/api.md §3): exact title, then partial title, then
    message content, newest `updated_at` first within each tier, id as final
    tiebreaker. Archived included; each result carries a `preview` snippet of
    the newest matching message (null for title matches)."""
    result = await db.execute(
        _SEARCH_CONVERSATIONS,
        {
            "user_id": str(identity.user_id),
            "q": query,
            "limit": limit,
            "offset": offset,
        },
    )
    rows: list[dict[str, Any]] = []
    for row in result.all():
        item = _row_to_dict(row)
        item["preview"] = (
            _match_snippet(row.matched_content, query)
            if row.matched_content is not None
            else None
        )
        rows.append(item)
    return rows


async def get_conversation(
    db: AsyncSession, identity: Identity, conversation_id: uuid.UUID
) -> dict[str, Any]:
    """One conversation; unowned/missing/deleted → ConversationNotFoundError."""
    result = await db.execute(
        _SELECT_CONVERSATION,
        {
            "conversation_id": str(conversation_id),
            "user_id": str(identity.user_id),
        },
    )
    row = result.one_or_none()
    if row is None:
        raise ConversationNotFoundError("conversation not found")
    return _row_to_dict(row)


async def get_selected_documents(
    db: AsyncSession, conversation_id: uuid.UUID
) -> list[dict[str, Any]]:
    """The conversation's selected documents with document metadata."""
    result = await db.execute(
        _SELECT_SELECTED_DOCUMENTS, {"conversation_id": str(conversation_id)}
    )
    return [
        {
            "id": row.id,
            "filename": row.filename,
            "status": row.status,
            "file_size_bytes": row.file_size_bytes,
            "total_chunks": row.total_chunks,
            "status_error": row.status_error,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in result.all()
    ]


async def update_conversation(
    db: AsyncSession,
    identity: Identity,
    conversation_id: uuid.UUID,
    *,
    title: str | None = None,
    document_ids: list[uuid.UUID] | None = None,
    pinned: bool | None = None,
    archived: bool | None = None,
) -> dict[str, Any]:
    """Rename, re-pin/archive, and/or fully replace the document selection.

    `document_ids`, when present, is a full replace: the previous selection is
    cleared and the new one linked (empty array = clear). Any rejected
    document leaves the whole selection unchanged (validate-then-write).
    `title`/`pinned`/`archived`, when present, are set; absent fields stay.
    """
    await get_conversation(db, identity, conversation_id)  # 404 on unowned/missing

    if document_ids is not None:
        await _require_ready_documents(db, identity, document_ids)
        await db.execute(_CLEAR_SELECTION, {"conversation_id": str(conversation_id)})
        for document_id in document_ids:
            await db.execute(
                _INSERT_SELECTION,
                {
                    "conversation_id": str(conversation_id),
                    "document_id": str(document_id),
                },
            )

    if title is not None or pinned is not None or archived is not None:
        result = await db.execute(
            _UPDATE_CONVERSATION,
            {
                "title": title,
                "pinned": pinned,
                "archived": archived,
                "conversation_id": str(conversation_id),
                "user_id": str(identity.user_id),
            },
        )
        return _row_to_dict(result.one())

    if document_ids is not None:
        await db.execute(
            _TOUCH_CONVERSATION,
            {
                "conversation_id": str(conversation_id),
                "user_id": str(identity.user_id),
            },
        )
    return await get_conversation(db, identity, conversation_id)


async def touch_conversation(
    db: AsyncSession, identity: Identity, conversation_id: uuid.UUID
) -> None:
    """Bump updated_at after chat activity so lists reorder (docs/api.md §3)."""
    await db.execute(
        _TOUCH_CONVERSATION,
        {
            "conversation_id": str(conversation_id),
            "user_id": str(identity.user_id),
        },
    )


async def delete_conversation(
    db: AsyncSession, identity: Identity, conversation_id: uuid.UUID
) -> None:
    """Soft-delete the conversation (docs/api.md §3); unowned → 404."""
    await get_conversation(db, identity, conversation_id)
    await db.execute(
        _DELETE_CONVERSATION,
        {
            "conversation_id": str(conversation_id),
            "user_id": str(identity.user_id),
        },
    )
