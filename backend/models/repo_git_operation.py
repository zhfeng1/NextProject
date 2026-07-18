from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base
from backend.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class RepoGitOperation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Audit record for destructive repository operations."""

    __tablename__ = "repo_git_operations"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    site_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    repo_name: Mapped[str] = mapped_column(String(255), default="")
    branch: Mapped[str] = mapped_column(String(255), nullable=False)
    target_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    before_sha: Mapped[str] = mapped_column(String(64), default="")
    after_sha: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="")
