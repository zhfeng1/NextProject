from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    title: str = "新会话"
    repo_ids: list[str] = Field(default_factory=list)
    provider: str = "codex"


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    provider: str = "codex"
    repo_ids: list[str] = Field(default_factory=list)
    current_url: str = ""
    selected_xpath: str = ""
    console_errors: str = ""


class MessageResponse(BaseModel):
    id: int
    conversation_id: str
    seq: int
    role: str
    content: str
    message_type: str = "text"
    provider: str = ""
    task_id: str = ""
    token_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class ConversationResponse(BaseModel):
    id: str
    site_id: str
    scope_type: str = "site"
    project_id: str = ""
    repo_ids: list[str] = Field(default_factory=list)
    provider: str = "codex"
    branch_name: str = ""
    worktree_root: str = ""
    completion_status: str = "active"
    completion_task_id: str = ""
    completion_error: str = ""
    cleanup_status: str = "retained"
    cleanup_error: str = ""
    completed_at: datetime | None = None
    title: str = "新会话"
    status: str = "active"
    summary_text: str = ""
    message_count: int = 0
    last_message_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    messages: list[MessageResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}
