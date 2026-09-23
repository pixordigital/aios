"""integration_outbox

Revision ID: a1b2c3d4e5f6
Revises: 933f3d3e65f4
Create Date: 2026-09-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '933f3d3e65f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('integration_outbox',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('peer', sa.String(length=20), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('business_trace_id', sa.String(length=64), nullable=True),
        sa.Column('idempotency_key', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_integration_outbox_peer', 'integration_outbox', ['peer'])
    op.create_index('ix_integration_outbox_event_type', 'integration_outbox', ['event_type'])
    op.create_index('ix_integration_outbox_business_trace_id', 'integration_outbox', ['business_trace_id'])
    op.create_index('ix_integration_outbox_idempotency_key', 'integration_outbox', ['idempotency_key'], unique=True)
    op.create_index('ix_integration_outbox_status', 'integration_outbox', ['status'])
    op.create_index('ix_integration_outbox_created_at', 'integration_outbox', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_integration_outbox_created_at', table_name='integration_outbox')
    op.drop_index('ix_integration_outbox_status', table_name='integration_outbox')
    op.drop_index('ix_integration_outbox_idempotency_key', table_name='integration_outbox')
    op.drop_index('ix_integration_outbox_business_trace_id', table_name='integration_outbox')
    op.drop_index('ix_integration_outbox_event_type', table_name='integration_outbox')
    op.drop_index('ix_integration_outbox_peer', table_name='integration_outbox')
    op.drop_table('integration_outbox')
