from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base
from backend.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class WorkflowRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workflow_runs"

    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    current_stage: Mapped[str] = mapped_column(String(32), default="research", nullable=False)
    stage_status_json: Mapped[dict] = mapped_column(SQLITE_JSON, default=dict)
    stage_artifacts_json: Mapped[dict] = mapped_column(SQLITE_JSON, default=dict)
    enabled_mcp_services_json: Mapped[list] = mapped_column(SQLITE_JSON, default=list)
    enabled_skill_ids_json: Mapped[list] = mapped_column(SQLITE_JSON, default=list)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    summary: Mapped[str] = mapped_column(Text, default="")
