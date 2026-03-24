from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base
from backend.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SiteVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "site_versions"
    __table_args__ = (UniqueConstraint("site_id", "version_number", name="uq_site_version"),)

    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[str | None] = mapped_column(ForeignKey("site_versions.id"), default=None)
    snapshot_url: Mapped[str] = mapped_column(String(500), default="")
    commit_message: Mapped[str] = mapped_column(Text, default="")
    diff_summary: Mapped[dict] = mapped_column(SQLITE_JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(36), default=None)
    is_deployed: Mapped[bool] = mapped_column(Boolean, default=False)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
