"""Store site versions as Git commits and remove template archives.

Revision ID: 20260727_0001
Revises: 20260715_0004
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260727_0001"
down_revision = "20260715_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("site_versions") as batch_op:
        batch_op.add_column(sa.Column("commit_sha", sa.String(length=40), nullable=False, server_default=""))
        batch_op.create_unique_constraint("uq_site_version_commit", ["site_id", "commit_sha"])
        batch_op.drop_column("snapshot_url")
    with op.batch_alter_table("templates") as batch_op:
        batch_op.drop_column("code_archive_url")


def downgrade() -> None:
    with op.batch_alter_table("templates") as batch_op:
        batch_op.add_column(sa.Column("code_archive_url", sa.String(length=500), nullable=True, server_default=""))
    with op.batch_alter_table("site_versions") as batch_op:
        batch_op.add_column(sa.Column("snapshot_url", sa.String(length=500), nullable=True, server_default=""))
        batch_op.drop_constraint("uq_site_version_commit", type_="unique")
        batch_op.drop_column("commit_sha")
