from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db
from backend.schemas.conversation import ConversationCreate, MessageCreate
from backend.services.conversation_service import conversation_service

router = APIRouter(prefix="/conversations")


@router.post("/site/{site_id}")
async def create_conversation(
    site_id: str,
    payload: ConversationCreate = None,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    title = payload.title if payload else "新会话"
    conv = await conversation_service.create_conversation(db, site_id, current_user, title=title)
    return {"ok": True, "conversation": conversation_service.serialize_conversation(conv)}


@router.get("/site/{site_id}")
async def list_conversations(
    site_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    convs = await conversation_service.list_conversations(db, site_id, current_user, limit=limit)
    return {
        "ok": True,
        "site_id": site_id,
        "conversations": [conversation_service.serialize_conversation(c) for c in convs],
    }


@router.get("/{conv_id}")
async def get_conversation(
    conv_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    conv = await conversation_service.get_conversation(db, conv_id, current_user)
    messages = await conversation_service.list_messages(db, conv_id, current_user)
    data = conversation_service.serialize_conversation(conv)
    data["messages"] = [conversation_service.serialize_message(m) for m in messages]
    return {"ok": True, "conversation": data}


@router.post("/{conv_id}/messages")
async def send_message(
    conv_id: str,
    payload: MessageCreate,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await conversation_service.send_message(
        db=db,
        conv_id=conv_id,
        current_user=current_user,
        content=payload.content,
        provider=payload.provider,
        current_url=payload.current_url,
        selected_xpath=payload.selected_xpath,
        console_errors=payload.console_errors,
    )
    return {"ok": True, **result}


@router.get("/{conv_id}/messages")
async def list_messages(
    conv_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    after_seq: int = Query(default=0, ge=0),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    messages = await conversation_service.list_messages(
        db, conv_id, current_user, limit=limit, after_seq=after_seq,
    )
    return {
        "ok": True,
        "conv_id": conv_id,
        "messages": [conversation_service.serialize_message(m) for m in messages],
    }


@router.delete("/{conv_id}")
async def archive_conversation(
    conv_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    conv = await conversation_service.archive_conversation(db, conv_id, current_user)
    return {"ok": True, "conversation": conversation_service.serialize_conversation(conv)}
