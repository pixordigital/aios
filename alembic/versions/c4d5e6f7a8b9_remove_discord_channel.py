"""remove discord channel connections

Revision ID: c4d5e6f7a8b9
Revises: a1b2c3d4e5f6
Create Date: 2026-10-02

Discord is no longer a supported channel. Any existing `channel_connections`
row with that type is deactivated rather than deleted: the row carries the
tenant's bot token in `config`, and silently dropping it would leave an
orphaned credential with no record that it existed.

Rows are deactivated, not removed, because `main.py` starts every active
channel at boot and `ChannelManager.build` raises on an unknown type — a
still-active row would log a traceback on every restart.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # sa.inspect rather than a query against information_schema: that catalog
    # does not exist in SQLite, so the existence check raised instead of
    # returning 0 and the migration could not run at all outside Postgres.
    if "channel_connections" not in sa.inspect(conn).get_table_names():
        return
    conn.execute(sa.text(
        "UPDATE channel_connections SET is_active = false WHERE channel_type = 'discord'"
    ))


def downgrade() -> None:
    """Re-activate. The Discord adapter is gone, so this only restores the flag
    on rows that still exist; re-adding the channel requires the code too."""
    conn = op.get_bind()
    if "channel_connections" not in sa.inspect(conn).get_table_names():
        return
    conn.execute(sa.text(
        "UPDATE channel_connections SET is_active = true WHERE channel_type = 'discord'"
    ))