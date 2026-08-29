"""Add module-level technical platform deployment configuration.

Revision ID: 20260829_0001
Revises: 20260727_0001
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260829_0001"
down_revision = "20260727_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tech_platform_deployment_modules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("dockerfile_path", sa.String(length=512), nullable=False),
        sa.Column(
            "build_context", sa.String(length=512), nullable=False, server_default="."
        ),
        sa.Column("app_name", sa.String(length=255), nullable=False),
        sa.Column(
            "namespace",
            sa.String(length=255),
            nullable=False,
            server_default="ocean-km",
        ),
        sa.Column(
            "harbor_project",
            sa.String(length=255),
            nullable=False,
            server_default="ocean-km",
        ),
        sa.Column("repository_name", sa.String(length=255), nullable=False),
        sa.Column("app_type", sa.String(length=16), nullable=False, server_default="2"),
        sa.Column(
            "container_port", sa.Integer(), nullable=False, server_default="8080"
        ),
        sa.Column("service_port", sa.Integer(), nullable=False, server_default="80"),
        sa.Column("config_map_template", sa.Text(), nullable=False, server_default=""),
        sa.Column("deployment_template", sa.Text(), nullable=False, server_default=""),
        sa.Column("service_template", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "platform_app_id", sa.String(length=128), nullable=False, server_default=""
        ),
        sa.Column(
            "is_available", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("last_task_id", sa.String(length=36), nullable=True),
        sa.Column(
            "last_image", sa.String(length=1024), nullable=False, server_default=""
        ),
        sa.Column(
            "last_commit_sha", sa.String(length=64), nullable=False, server_default=""
        ),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="idle"
        ),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["last_task_id"], ["agent_tasks.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "site_id", "dockerfile_path", name="uq_tech_platform_module_site_dockerfile"
        ),
    )
    op.create_index(
        "ix_tech_platform_deployment_modules_project_id",
        "tech_platform_deployment_modules",
        ["project_id"],
    )
    op.create_index(
        "ix_tech_platform_deployment_modules_site_id",
        "tech_platform_deployment_modules",
        ["site_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tech_platform_deployment_modules_site_id",
        table_name="tech_platform_deployment_modules",
    )
    op.drop_index(
        "ix_tech_platform_deployment_modules_project_id",
        table_name="tech_platform_deployment_modules",
    )
    op.drop_table("tech_platform_deployment_modules")
