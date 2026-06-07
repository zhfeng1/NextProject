"""Refactor MCP, skills, task board, and task repositories.

Revision ID: 20260623_0001
Revises: 20260423_0002
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260623_0001"
down_revision = "20260423_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    cascade = " CASCADE" if dialect == "postgresql" else ""

    for table in ("site_skill_bindings", "skills", "user_mcp_services", "workflow_runs", "task_logs", "tasks"):
        op.execute(sa.text(f"DROP TABLE IF EXISTS {table}{cascade}"))

    json_type = sa.JSON()
    op.create_table(
        "mcp_service_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("service_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=True),
        sa.Column("scope_type", sa.String(length=16), server_default="global", nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("site_id", sa.String(length=36), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("config_json", json_type, nullable=True),
        sa.Column("required_fields_json", json_type, nullable=True),
        sa.Column("supports_config", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), server_default="", nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("service_id", "scope_type", "project_id", "site_id", name="uq_mcp_service_scope"),
    )
    op.create_index("ix_mcp_service_configs_service_id", "mcp_service_configs", ["service_id"])
    op.create_index("ix_mcp_service_configs_scope_type", "mcp_service_configs", ["scope_type"])
    op.create_index("ix_mcp_service_configs_project_id", "mcp_service_configs", ["project_id"])
    op.create_index("ix_mcp_service_configs_site_id", "mcp_service_configs", ["site_id"])

    op.create_table(
        "skill_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=True),
        sa.Column("scope_type", sa.String(length=16), server_default="global", nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("site_id", sa.String(length=36), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("content", sa.Text(), server_default="", nullable=False),
        sa.Column("triggers_json", json_type, nullable=True),
        sa.Column("source_type", sa.String(length=32), server_default="manual", nullable=False),
        sa.Column("source_url", sa.String(length=512), server_default="", nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "scope_type", "project_id", "site_id", name="uq_skill_scope_name"),
    )
    op.create_index("ix_skill_configs_scope_type", "skill_configs", ["scope_type"])
    op.create_index("ix_skill_configs_project_id", "skill_configs", ["project_id"])
    op.create_index("ix_skill_configs_site_id", "skill_configs", ["site_id"])

    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("site_id", sa.String(length=36), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=255), server_default="", nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("priority", sa.String(length=16), server_default="medium", nullable=False),
        sa.Column("assignee", sa.String(length=255), server_default="", nullable=False),
        sa.Column("board_status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("provider", sa.String(length=32), server_default="", nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("payload_json", json_type, nullable=True),
        sa.Column("workflow_stages_json", json_type, nullable=True),
        sa.Column("runtime_config_dir", sa.String(length=512), server_default="", nullable=False),
        sa.Column("result_json", json_type, nullable=True),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
        sa.Column("celery_task_id", sa.String(length=64), server_default="", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_tasks_site_id", "agent_tasks", ["site_id"])
    op.create_index("ix_agent_tasks_project_id", "agent_tasks", ["project_id"])
    op.create_index("ix_agent_tasks_board_status", "agent_tasks", ["board_status"])
    op.create_index("ix_agent_tasks_task_type", "agent_tasks", ["task_type"])

    op.create_table(
        "agent_task_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("level", sa.String(length=16), server_default="INFO", nullable=True),
        sa.Column("line", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["agent_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_task_logs_task_id", "agent_task_logs", ["task_id"])

    op.create_table(
        "task_repositories",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("repo_path", sa.String(length=512), server_default="", nullable=True),
        sa.Column("before_sha", sa.String(length=64), server_default="", nullable=True),
        sa.Column("after_sha", sa.String(length=64), server_default="", nullable=True),
        sa.Column("changed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("commit_message", sa.Text(), server_default="", nullable=True),
        sa.Column("rollback_status", sa.String(length=32), server_default="", nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["agent_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id", "site_id"),
    )


def downgrade() -> None:
    for table in ("task_repositories", "agent_task_logs", "agent_tasks", "skill_configs", "mcp_service_configs"):
        op.drop_table(table)
