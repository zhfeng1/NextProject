from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    title: str = "新会话"


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    provider: str = "codex"
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
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class ConversationResponse(BaseModel):
    id: str
    site_id: str
    title: str = "新会话"
    status: str = "active"
    summary_text: str = ""
    message_count: int = 0
    last_message_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    messages: list[MessageResponse] = []

    model_config = {"from_attributes": True}
