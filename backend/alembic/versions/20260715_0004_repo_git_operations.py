"""Add repository Git operation audit records.

Revision ID: 20260715_0004
Revises: 20260715_0003
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260715_0004"
down_revision = "20260715_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repo_git_operations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("repo_name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=False),
        sa.Column("target_sha", sa.String(length=64), nullable=False),
        sa.Column("before_sha", sa.String(length=64), server_default="", nullable=False),
        sa.Column("after_sha", sa.String(length=64), server_default="", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="running", nullable=False),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_repo_git_operations_project_id", "repo_git_operations", ["project_id"])
    op.create_index("ix_repo_git_operations_site_id", "repo_git_operations", ["site_id"])
    op.create_index("ix_repo_git_operations_conversation_id", "repo_git_operations", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_repo_git_operations_conversation_id", table_name="repo_git_operations")
    op.drop_index("ix_repo_git_operations_site_id", table_name="repo_git_operations")
    op.drop_index("ix_repo_git_operations_project_id", table_name="repo_git_operations")
    op.drop_table("repo_git_operations")
