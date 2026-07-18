from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user, get_db, require_role
from backend.schemas.conversation import ConversationCreate, MessageCreate
from backend.services.conversation_service import conversation_service
from backend.services.git_history_service import git_history_service

router = APIRouter(prefix="/conversations")


@router.post("/site/{site_id}")
async def create_conversation(
    site_id: str,
    payload: ConversationCreate | None = None,
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


@router.post("/project/{project_id}")
async def create_project_conversation(
    project_id: str,
    payload: ConversationCreate | None = None,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    title = payload.title if payload else "新会话"
    repo_ids = payload.repo_ids if payload else []
    provider = payload.provider if payload else "codex"
    conv = await conversation_service.create_project_conversation(
        db,
        project_id,
        current_user,
        title=title,
        repo_ids=repo_ids,
        provider=provider,
    )
    return {"ok": True, "conversation": conversation_service.serialize_conversation(conv)}


@router.get("/project/{project_id}")
async def list_project_conversations(
    project_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    status: str = Query(default="active", pattern="^(active|archived)$"),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    convs = await conversation_service.list_project_conversations(
        db,
        project_id,
        current_user,
        limit=limit,
        status=status,
    )
    return {
        "ok": True,
        "project_id": project_id,
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


@router.get("/{conv_id}/git")
async def get_conversation_git_state(
    conv_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    state = await conversation_service.get_git_state(db, conv_id, current_user)
    return {"ok": True, "git": state}


@router.get("/{conv_id}/repos/{repo_id}/git/diff")
async def get_conversation_repo_file_diff(
    conv_id: str,
    repo_id: str,
    path: str = Query(min_length=1, max_length=2000),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    file_diff = await conversation_service.get_git_file_diff(
        db,
        conv_id,
        repo_id,
        path,
        current_user,
    )
    return {"ok": True, "file": file_diff}


@router.get("/{conv_id}/repos/{repo_id}/git/graph")
async def get_conversation_repo_git_graph(
    conv_id: str,
    repo_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    graph = await conversation_service.get_git_graph(
        db,
        conv_id,
        repo_id,
        current_user,
        limit=limit,
        skip=skip,
    )
    return {"ok": True, "graph": graph}


@router.post("/{conv_id}/repos/{repo_id}/git/rollback")
async def rollback_conversation_repo_commit(
    conv_id: str,
    repo_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    current_user: object = Depends(require_role("developer")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    operation, graph = await conversation_service.rollback_repo_to_commit(
        db,
        conv_id,
        repo_id,
        current_user,
        commit_sha=str(payload.get("commit_sha") or "").strip(),
    )
    return {
        "ok": True,
        "operation": git_history_service.serialize_operation(operation),
        "graph": graph,
    }


@router.post("/{conv_id}/complete")
async def complete_conversation(
    conv_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await conversation_service.complete_conversation(db, conv_id, current_user)
    return {"ok": True, **result}


@router.post("/{conv_id}/cleanup")
async def cleanup_conversation(
    conv_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    conv = await conversation_service.cleanup_conversation(db, conv_id, current_user)
    git_state = await conversation_service.get_git_state(db, conv_id, current_user)
    return {
        "ok": True,
        "conversation": conversation_service.serialize_conversation(conv),
        "git": git_state,
    }


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
        repo_ids=payload.repo_ids,
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


@router.post("/{conv_id}/restore")
async def restore_conversation(
    conv_id: str,
    current_user: object = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    conv = await conversation_service.restore_conversation(db, conv_id, current_user)
    return {"ok": True, "conversation": conversation_service.serialize_conversation(conv)}
