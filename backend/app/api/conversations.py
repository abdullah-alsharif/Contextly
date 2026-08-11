"""Conversations router: CRUD + document selection (docs/api.md §3).

Every endpoint is guarded by the router-level get_current_user dependency, so
unauthenticated requests get 401 by construction (contracts/auth.md §1). Error
mapping (docs/api.md §6, docs/security.md §2): 404 for unowned/missing/deleted
conversations AND for rejected documents (deliberately ambiguous — never
reveals existence or ownership), 422 for schema violations. PATCH semantics:
full replace of document_ids when present, empty array clears (docs/api.md §3).
"""

from __future__ import annotations

from typing import Any

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.deps import get_current_user
from app.core.security.identity import Identity
from app.db.session import get_db
from app.schemas.conversation import (
    ConversationDetailOut,
    ConversationIn,
    ConversationOut,
)
from app.services.conversations import (
    ConversationNotFoundError,
    DocumentSelectionError,
    create_conversation,
    delete_conversation,
    get_conversation,
    get_selected_documents,
    list_conversations,
    update_conversation,
)

router = APIRouter(
    prefix="/conversations",
    tags=["conversations"],
    dependencies=[Depends(get_current_user)],
)


@router.post("", response_model=ConversationOut, status_code=201)
async def create_conversation_endpoint(
    body: ConversationIn,
    identity: Identity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a conversation with an optional validated document selection."""
    try:
        return await create_conversation(
            db,
            identity,
            title=body.title,
            document_ids=body.document_ids,
        )
    except DocumentSelectionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("", response_model=list[ConversationOut])
async def list_conversations_endpoint(
    identity: Identity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """The caller's conversations, newest first (docs/api.md §3)."""
    return await list_conversations(db, identity)


@router.get("/{conversation_id}", response_model=ConversationDetailOut)
async def get_conversation_endpoint(
    conversation_id: uuid.UUID,
    identity: Identity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Detail: the conversation plus its selected documents."""
    try:
        conversation = await get_conversation(db, identity, conversation_id)
        documents = await get_selected_documents(db, conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"conversation": conversation, "documents": documents}


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def update_conversation_endpoint(
    conversation_id: uuid.UUID,
    body: ConversationIn,
    identity: Identity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Rename and/or fully replace the document selection (docs/api.md §3)."""
    try:
        return await update_conversation(
            db,
            identity,
            conversation_id,
            title=body.title,
            document_ids=body.document_ids,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DocumentSelectionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation_endpoint(
    conversation_id: uuid.UUID,
    identity: Identity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Soft-delete the conversation; unowned/missing behave as 404."""
    try:
        await delete_conversation(db, identity, conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)
