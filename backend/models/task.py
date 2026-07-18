from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base
from backend.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"


class AgentTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_tasks"

    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(16), default="medium")
    assignee: Mapped[str] = mapped_column(String(255), default="")
    board_status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), default="")
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=TaskStatus.QUEUED.value)
    payload_json: Mapped[dict] = mapped_column(SQLITE_JSON, default=dict)
    workflow_stages_json: Mapped[list] = mapped_column(SQLITE_JSON, default=list)
    runtime_config_dir: Mapped[str] = mapped_column(String(512), default="")
    result_json: Mapped[dict] = mapped_column(SQLITE_JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    celery_task_id: Mapped[str] = mapped_column(String(64), default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class AgentTaskLog(Base):
    __tablename__ = "agent_task_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("agent_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    level: Mapped[str] = mapped_column(String(16), default="INFO")
    line: Mapped[str] = mapped_column(Text, nullable=False)


class TaskRepository(TimestampMixin, Base):
    __tablename__ = "task_repositories"

    task_id: Mapped[str] = mapped_column(ForeignKey("agent_tasks.id", ondelete="CASCADE"), primary_key=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True)
    repo_path: Mapped[str] = mapped_column(String(512), default="")
    before_sha: Mapped[str] = mapped_column(String(64), default="")
    after_sha: Mapped[str] = mapped_column(String(64), default="")
    changed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    commit_message: Mapped[str] = mapped_column(Text, default="")
    rollback_status: Mapped[str] = mapped_column(String(32), default="")
