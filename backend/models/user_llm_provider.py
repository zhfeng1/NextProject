import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from backend.models.base import Base
from backend.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class UserLLMProvider(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_llm_providers"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, default="global", index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    base_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    api_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    models: Mapped[dict | list] = mapped_column(JSON, nullable=False, default=list)
    format: Mapped[str] = mapped_column(String(20), nullable=False, default="responses")
    formats_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    enabled_formats_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
