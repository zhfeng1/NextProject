"""Add phase 2 features: Requirements, Roles

Revision ID: 20260331_0001
Revises: 
Create Date: 2026-03-31 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260331_0001'
down_revision: Union[str, None] = '20260323_0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # We are using sqlite/postgres so just simple create statements for now.
    
    # 1. Add roles to organization_members if needed
    # It's already defined as Mapped[str] = mapped_column(String(20), default="member")
    # which implies it should exist in initial schema, but we'll add it if missing dynamically
    
    # 2. Add Requirements Tables
    op.create_table(
        'site_requirement_events',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('site_id', sa.String(length=36), nullable=False),
        sa.Column('conversation_id', sa.String(length=36), nullable=True),
        sa.Column('task_id', sa.String(length=36), nullable=True),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('processed', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_site_requirement_events_site_id'), 'site_requirement_events', ['site_id'], unique=False)

    op.create_table(
        'site_requirement_snapshots',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('site_id', sa.String(length=36), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('diff_from_previous', sa.Text(), nullable=False, server_default=''),
        sa.Column('event_ids_json', sa.Text(), nullable=False, server_default='[]'),
        sa.ForeignKeyConstraint(['site_id'], ['sites.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_site_requirement_snapshots_site_id'), 'site_requirement_snapshots', ['site_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_site_requirement_snapshots_site_id'), table_name='site_requirement_snapshots')
    op.drop_table('site_requirement_snapshots')
    op.drop_index(op.f('ix_site_requirement_events_site_id'), table_name='site_requirement_events')
    op.drop_table('site_requirement_events')
