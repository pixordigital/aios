"""add governance_config to agents"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9051a2b3c4d6"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # governance_config already added by b3c4d5e6f7a8 (governance_oauth_tenant_hardening).
    # This revision was a duplicate branch; now a no-op so merging the fork is safe.
    pass


def downgrade() -> None:
    op.drop_column("agents", "governance_config")
