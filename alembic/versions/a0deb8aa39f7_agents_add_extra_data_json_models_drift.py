"""agents: add extra_data JSON (models drift)

Revision ID: a0deb8aa39f7
Revises: 834529df9a09
Create Date: 2026-10-02 15:09:51.309686

The Agent model carries extra_data (project_path, custom config) but no
migration ever created the column: fresh databases built purely through
alembic lack it, while create_all-built ones (including production) have it.
CI's `alembic check` would have caught this, but it runs with `|| echo ...
ignored`. Guarded add-column so it is a no-op where the column exists.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a0deb8aa39f7'
down_revision: Union[str, Sequence[str], None] = '834529df9a09'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "agents"


def _columns() -> set:
    insp = sa.inspect(op.get_bind())
    if TABLE not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(TABLE)}


def upgrade() -> None:
    if "extra_data" not in _columns():
        op.add_column(TABLE, sa.Column("extra_data", sa.JSON(), nullable=True))


def downgrade() -> None:
    if "extra_data" in _columns():
        op.drop_column(TABLE, "extra_data")
