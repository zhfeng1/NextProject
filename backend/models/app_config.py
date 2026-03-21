from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base
from backend.models.mixins import TimestampMixin


class AppConfig(TimestampMixin, Base):
    __tablename__ = "app_config"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    llm_mode: Mapped[str] = mapped_column(String(32), default="responses")
    llm_base_url: Mapped[str] = mapped_column(String(255), default="https://api.openai.com/v1")
    llm_api_key: Mapped[str] = mapped_column(Text, default="")
    llm_model: Mapped[str] = mapped_column(String(128), default="gpt-4.1-mini")
    codex_client_id: Mapped[str] = mapped_column(String(255), default="")
    codex_client_secret: Mapped[str] = mapped_column(String(255), default="")
    codex_redirect_uri: Mapped[str] = mapped_column(String(255), default="")
    codex_access_token: Mapped[str] = mapped_column(Text, default="")
    codex_mcp_url: Mapped[str] = mapped_column(String(255), default="")
