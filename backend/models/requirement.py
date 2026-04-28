from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base
from backend.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

class SiteRequirementEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "site_requirement_events"

    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), default=None)
    task_id: Mapped[str | None] = mapped_column(String(36), default=None)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False) # chat_message, pipeline_run, etc
    content: Mapped[str] = mapped_column(Text, nullable=False)
    processed: Mapped[bool] = mapped_column(default=False)

class SiteRequirementSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "site_requirement_snapshots"

    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    diff_from_previous: Mapped[str] = mapped_column(Text, default="")
    event_ids_json: Mapped[str] = mapped_column(Text, default="[]")
