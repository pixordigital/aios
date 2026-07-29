"""add governance_config to agents"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9051a2b3c4d6"
down_revision: Union[str, None] = "9051a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("governance_config", sa.JSON, nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("agents", "governance_config")
