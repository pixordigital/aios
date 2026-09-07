"""add tokens/cost_usd to workflow_runs (automations 500 fix)

Revision ID: f9a2b3c4d5e6
Revises: e8f1a2b3c4d5
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "f9a2b3c4d5e6"
down_revision: Union[str, None] = "e8f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # workflow_runs table with tokens/cost_usd already created in 9051a2b3c4d9
    pass

def downgrade() -> None:
    # no-op: workflow_runs created in earlier revision
    pass
