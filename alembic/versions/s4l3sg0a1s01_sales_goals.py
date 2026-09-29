"""sales_goals table for monthly targets (internal tool).

Idempotent: init_db() runs SQLAlchemy create_all on startup, so the table may
already exist by the time this migration runs. An unguarded create_table made
`alembic upgrade head` fail on every container boot and pinned alembic_version
at 97c400a6f914.
"""

revision = "s4l3sg0a1s01"
down_revision = "97c400a6f914"

from alembic import op
import sqlalchemy as sa

TABLE = "sales_goals"


def _exists(conn) -> bool:
    return sa.inspect(conn).has_table(TABLE)


def upgrade():
    conn = op.get_bind()
    if not _exists(conn):
        op.create_table(
            TABLE,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("year_month", sa.String(7), nullable=False),
            sa.Column("target_brl", sa.Float(), server_default="0"),
            sa.Column("team_id", sa.String(36), sa.ForeignKey("teams.id"), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    existing = {i["name"] for i in sa.inspect(conn).get_indexes(TABLE)} if _exists(conn) else set()
    if "ix_sales_goals_year_month" not in existing:
        op.create_index("ix_sales_goals_year_month", TABLE, ["year_month"])
    if "ix_sales_goals_team" not in existing:
        op.create_index("ix_sales_goals_team", TABLE, ["team_id"])


def downgrade():
    conn = op.get_bind()
    if not _exists(conn):
        return
    op.drop_table(TABLE)
