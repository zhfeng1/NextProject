"""Remove the technical platform namespace database default.

Revision ID: 20260829_0002
Revises: 20260829_0001
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260829_0002"
down_revision = "20260829_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "tech_platform_deployment_modules",
        "namespace",
        existing_type=sa.String(length=255),
        existing_nullable=False,
        server_default=None,
    )


def downgrade() -> None:
    op.alter_column(
        "tech_platform_deployment_modules",
        "namespace",
        existing_type=sa.String(length=255),
        existing_nullable=False,
        server_default="ocean-km",
    )
