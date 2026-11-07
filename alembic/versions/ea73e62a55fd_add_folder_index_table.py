"""add folder_index table

Revision ID: ea73e62a55fd
Revises: r4s5t6u7v8w9
Create Date: 2026-11-06 19:17:00.567141

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ea73e62a55fd'
down_revision: Union[str, Sequence[str], None] = 'r4s5t6u7v8w9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
