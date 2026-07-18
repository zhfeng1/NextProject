"""Add conversation worktrees and repository main branches.

Revision ID: 20260714_0001
Revises: 20260702_0001
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260714_0001"
down_revision = "20260702_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sites", sa.Column("main_branch", sa.String(length=255), server_default="", nullable=False))
    op.add_column("conversations", sa.Column("provider", sa.String(length=32), server_default="codex", nullable=False))
    op.add_column("conversations", sa.Column("branch_name", sa.String(length=255), server_default="", nullable=False))
    op.add_column("conversations", sa.Column("worktree_root", sa.String(length=512), server_default="", nullable=False))
    op.add_column("conversations", sa.Column("git_repos_json", sa.JSON(), server_default=sa.text("'[]'"), nullable=False))
    op.add_column("conversations", sa.Column("diff_snapshot_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False))
    op.add_column("conversations", sa.Column("completion_status", sa.String(length=20), server_default="active", nullable=False))
    op.add_column("conversations", sa.Column("completion_task_id", sa.String(length=36), server_default="", nullable=False))
    op.add_column("conversations", sa.Column("completion_error", sa.Text(), server_default="", nullable=False))
    op.add_column("conversations", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "completed_at")
    op.drop_column("conversations", "completion_error")
    op.drop_column("conversations", "completion_task_id")
    op.drop_column("conversations", "completion_status")
    op.drop_column("conversations", "diff_snapshot_json")
    op.drop_column("conversations", "git_repos_json")
    op.drop_column("conversations", "worktree_root")
    op.drop_column("conversations", "branch_name")
    op.drop_column("conversations", "provider")
    op.drop_column("sites", "main_branch")
