"""merge outbox + budgets

Revision ID: 97c400a6f914
Revises: 3ea6512191ab, a1b2c3d4e5f6
Create Date: 2026-09-23 15:13:51.215297

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '97c400a6f914'
down_revision: Union[str, Sequence[str], None] = ('3ea6512191ab', 'a1b2c3d4e5f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
