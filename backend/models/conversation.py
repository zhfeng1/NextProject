from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base
from backend.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """多轮对话会话"""
    __tablename__ = "conversations"

    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(16), default="site", nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), default="新会话")
    repo_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    provider: Mapped[str] = mapped_column(String(32), default="codex")
    provider_session_id: Mapped[str] = mapped_column(String(255), default="")
    branch_name: Mapped[str] = mapped_column(String(255), default="")
    worktree_root: Mapped[str] = mapped_column(String(512), default="")
    git_repos_json: Mapped[list] = mapped_column(JSON, default=list)
    diff_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    completion_status: Mapped[str] = mapped_column(String(20), default="active")
    completion_task_id: Mapped[str] = mapped_column(String(36), default="")
    completion_error: Mapped[str] = mapped_column(Text, default="")
    cleanup_status: Mapped[str] = mapped_column(String(20), default="retained")
    cleanup_error: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | archived
    summary_text: Mapped[str] = mapped_column(Text, default="")
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class ConversationMessage(Base):
    """对话消息"""
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant | system | tool
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str] = mapped_column(String(20), default="text")  # text | task_ref
    provider: Mapped[str] = mapped_column(String(32), default="")
    task_id: Mapped[str] = mapped_column(String(36), default="")
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
