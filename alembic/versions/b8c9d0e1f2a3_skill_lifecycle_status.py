"""Skills lifecycle status column.

revision = "b8c9d0e1f2a3"
down_revision = "w5x6y7z8a9b0"

Requires founder approval for publish/deprecate; see
aios/governance/skill_lifecycle.py.
"""

from alembic import op
import sqlalchemy as sa

revision = "b8c9d0e1f2a3"
down_revision = "w5x6y7z8a9b0"


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    if "skills" not in sa.inspect(op.get_bind()).get_table_names():
        return
    cols = _columns("skills")
    if "status" not in cols:
        op.add_column(
            "skills",
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        )
    if "ix_skills_status" not in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("skills")}:
        op.create_index("ix_skills_status", "skills", ["status"])


def downgrade():
    if "skills" not in sa.inspect(op.get_bind()).get_table_names():
        return
    cols = _columns("skills")
    if "status" in cols:
        op.drop_column("skills", "status")
