"""merge_heads

Revision ID: ee188fe33d7f
Revises: 5def150444e3, g3a4b5c6d7e8
Create Date: 2026-09-22 11:09:16.628507

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ee188fe33d7f'
down_revision: Union[str, Sequence[str], None] = ('5def150444e3', 'g3a4b5c6d7e8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
