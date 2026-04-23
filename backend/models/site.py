from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base
from backend.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SiteStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    BUILDING = "building"
    ERROR = "error"


class Site(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sites"

    site_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True, default=None
    )
    status: Mapped[str] = mapped_column(String(20), default=SiteStatus.STOPPED.value, nullable=False)
    port: Mapped[int | None] = mapped_column(Integer, unique=True, default=None)
    template_id: Mapped[str | None] = mapped_column(ForeignKey("templates.id"), default=None)
    root_path: Mapped[str] = mapped_column(String(512), default="")
    preview_url: Mapped[str] = mapped_column(String(255), default="")
    internal_url: Mapped[str] = mapped_column(String(255), default="")
    config: Mapped[dict] = mapped_column(SQLITE_JSON, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class SiteDeployConfig(TimestampMixin, Base):
    __tablename__ = "site_deploy_config"

    site_id: Mapped[str] = mapped_column(ForeignKey("sites.site_id", ondelete="CASCADE"), primary_key=True)
    target_type: Mapped[str] = mapped_column(String(32), default="local")
    system_api_base: Mapped[str] = mapped_column(String(255), default="")
    system_id: Mapped[str] = mapped_column(String(128), default="")
    app_id: Mapped[str] = mapped_column(String(128), default="")
    harbor_domain: Mapped[str] = mapped_column(String(255), default="")
    harbor_domain_public: Mapped[str] = mapped_column(String(255), default="")
    harbor_namespace: Mapped[str] = mapped_column(String(255), default="")
    module_name: Mapped[str] = mapped_column(String(128), default="")
    login_tel: Mapped[str] = mapped_column(Text, default="")
    login_password: Mapped[str] = mapped_column(Text, default="")
    login_random: Mapped[str] = mapped_column(String(64), default="")
    login_path: Mapped[str] = mapped_column(String(255), default="/apollo/user/login")
    deploy_path: Mapped[str] = mapped_column(String(255), default="/devops/cicd/v1.0/job/deployByImage")
    extra_headers_json: Mapped[str] = mapped_column(Text, default="{}")


class SiteProviderConfig(TimestampMixin, Base):
    __tablename__ = "site_provider_config"

    site_id: Mapped[str] = mapped_column(ForeignKey("sites.site_id", ondelete="CASCADE"), primary_key=True)
    codex_cmd: Mapped[str] = mapped_column(Text, default="")
    claude_cmd: Mapped[str] = mapped_column(Text, default="")
    gemini_cmd: Mapped[str] = mapped_column(Text, default="")
    codex_auth_cmd: Mapped[str] = mapped_column(Text, default="")
    claude_auth_cmd: Mapped[str] = mapped_column(Text, default="")
    gemini_auth_cmd: Mapped[str] = mapped_column(Text, default="")
