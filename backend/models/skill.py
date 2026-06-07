from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base
from backend.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SkillConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "skill_configs"
    __table_args__ = (
        UniqueConstraint("name", "scope_type", "project_id", "site_id", name="uq_skill_scope_name"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, default="global", index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), nullable=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    triggers_json: Mapped[list] = mapped_column(SQLITE_JSON, default=list)
    source_type: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), default="")
