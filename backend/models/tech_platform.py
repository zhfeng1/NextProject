from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base
from backend.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class TechPlatformDeploymentModule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tech_platform_deployment_modules"
    __table_args__ = (
        UniqueConstraint(
            "site_id", "dockerfile_path", name="uq_tech_platform_module_site_dockerfile"
        ),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    site_id: Mapped[str] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dockerfile_path: Mapped[str] = mapped_column(String(512), nullable=False)
    build_context: Mapped[str] = mapped_column(String(512), nullable=False, default=".")
    app_name: Mapped[str] = mapped_column(String(255), nullable=False)
    namespace: Mapped[str] = mapped_column(
        String(255), nullable=False, default="ocean-km"
    )
    harbor_project: Mapped[str] = mapped_column(
        String(255), nullable=False, default="ocean-km"
    )
    repository_name: Mapped[str] = mapped_column(String(255), nullable=False)
    app_type: Mapped[str] = mapped_column(String(16), nullable=False, default="2")
    container_port: Mapped[int] = mapped_column(Integer, nullable=False, default=8080)
    service_port: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    config_map_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    deployment_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    service_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    platform_app_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default=""
    )
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_tasks.id", ondelete="SET NULL"), nullable=True, default=None
    )
    last_image: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    last_commit_sha: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="idle")
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_deployed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
