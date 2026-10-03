"""merge: rejoin discord-removal branch to mainline

c4d5e6f7a8b9 (remove discord channel connections) was authored with
down_revision a1b2c3d4e5f6, an old revision that had already been merged
into the mainline at 97c400a6f914. It therefore formed a side branch that
never rejoined, leaving two heads: a0deb8aa39f7 and c4d5e6f7a8b9.

FAILED: Multiple head revisions are present for given argument 'head'; please specify a specific target revision, '<branchname>@head' to narrow to a specific head, or 'heads' for all heads fails outright with "Multiple head revisions are
present", so no database can be migrated. CI hid this because that step
ends in `|| echo "alembic check: sqlite autogenerate noise ignored"`,
which swallows the failure; the test suite then ran against a schema built
by Base.metadata.create_all, never by a migration.

Merging rather than repointing c4d5e6f7a8b9's down_revision, which would
rewrite applied history. Both heads are guarded, so either order is safe,
and this matches the two merge revisions already in this chain.

Revision ID: f7a8b9c0d1e2
Revises: a0deb8aa39f7, c4d5e6f7a8b9
Create Date: 2026-10-03 22:32:19.339666

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, Sequence[str], None] = ('a0deb8aa39f7', 'c4d5e6f7a8b9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
