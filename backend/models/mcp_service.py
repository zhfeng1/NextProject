from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base
from backend.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class UserMcpService(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_mcp_services"
    __table_args__ = (
        UniqueConstraint("user_id", "service_id", name="uq_user_mcp_services_user_id_service_id"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    service_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    config_json: Mapped[dict] = mapped_column(SQLITE_JSON, default=dict)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, default=None)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_error: Mapped[str] = mapped_column(Text, default="")
