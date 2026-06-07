from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base
from backend.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class McpServiceConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcp_service_configs"
    __table_args__ = (
        UniqueConstraint(
            "service_id",
            "scope_type",
            "project_id",
            "site_id",
            name="uq_mcp_service_scope",
        ),
    )

    service_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, default="global", index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), nullable=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config_json: Mapped[dict] = mapped_column(SQLITE_JSON, default=dict)
    required_fields_json: Mapped[list] = mapped_column(SQLITE_JSON, default=list)
    supports_config: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, default=None)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_error: Mapped[str] = mapped_column(Text, default="")
