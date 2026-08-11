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
    select id, title, created_at, updated_at
    from conversations
    where id = :conversation_id and user_id = :user_id and deleted_at is null
    """
)

_SELECT_CONVERSATIONS = text(
    """
    select id, title, created_at, updated_at
    from conversations
    where user_id = :user_id and deleted_at is null
    order by updated_at desc
    """
)

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
    returning id, title, created_at, updated_at
    """
)

_UPDATE_CONVERSATION = text(
    """
    update conversations
    set title = :title, updated_at = now()
    where id = :conversation_id and user_id = :user_id and deleted_at is null
    returning id, title, created_at, updated_at
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


class ConversationRow(dict[str, Any]):
    """Conversation row with attribute access (id, title, created_at, updated_at)."""

    __getattr__ = dict.__getitem__


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
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
    db: AsyncSession, identity: Identity
) -> list[dict[str, Any]]:
    """The caller's conversations, newest first (docs/api.md §3)."""
    result = await db.execute(_SELECT_CONVERSATIONS, {"user_id": str(identity.user_id)})
    return [_row_to_dict(row) for row in result.all()]


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
) -> dict[str, Any]:
    """Rename and/or fully replace the document selection (docs/api.md §3).

    document_ids, when present, is a full replace: the previous selection is
    cleared and the new one linked (empty array = clear). Any rejected
    document leaves the whole selection unchanged (validate-then-write).
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

    if title is not None:
        result = await db.execute(
            _UPDATE_CONVERSATION,
            {
                "title": title,
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
