from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, PrimaryKeyConstraint, String, Text
from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base
from backend.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Skill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "skills"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    scope: Mapped[str] = mapped_column(String(32), default="global", nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    triggers_json: Mapped[list] = mapped_column(SQLITE_JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), default="")


class SiteSkillBinding(TimestampMixin, Base):
    __tablename__ = "site_skill_bindings"
    __table_args__ = (
        PrimaryKeyConstraint("site_id", "skill_id", name="pk_site_skill_bindings"),
    )

    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), nullable=False)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
