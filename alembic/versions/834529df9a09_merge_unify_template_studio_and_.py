"""merge: unify template studio and collaboration chains

Revision ID: 834529df9a09
Revises: f1a2b3c4d5e6, n3o4p5q6r7s8
Create Date: 2026-10-02 11:30:22.878650

Two independent heads existed after consolidating the agent-audit branch with
the WhatsApp template studio:

    z6a7b8c9d0e1 -> f1a2b3c4d5e6          (template studio)
    z6a7b8c9d0e1 -> b7c8d9e0f1a2 -> ... -> n3o4p5q6r7s8   (collaboration)

This revision joins them. It exists so that NO existing migration has to be
rewritten: both f1a2b3c4d5e6 and the collaboration chain are already applied to
production databases, so editing their down_revision pointers would change the
meaning of history Alembic has already recorded.

Do not "fix" the multiple-heads error by rewiring down_revision. An attempt to
do exactly that pointed f1a2b3c4d5e6 at m2n3o4p5q6r7 and n3o4p5q6r7s8 back at
f1a2b3c4d5e6, which is a cycle: f1a2b3c4d5e6 -> m2n3o4p5q6r7 -> ... ->
n3o4p5q6r7s8 -> f1a2b3c4d5e6. The empty upgrade() below is the correct and
intentional merge behaviour.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '834529df9a09'
down_revision: Union[str, Sequence[str], None] = ('f1a2b3c4d5e6', 'n3o4p5q6r7s8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge point only -- both parent chains already ran their own DDL."""
    pass


def downgrade() -> None:
    """Merge point only; nothing to undo."""
    pass
