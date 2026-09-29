"""blacklist + tamper columns — prevenção fraude re-cadastro

Idempotent: init_db() runs create_all on startup, so these may already exist.
An unguarded create_table/add_column breaks `alembic upgrade head` on a database
whose schema was created outside this migration.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import JSON

revision = "h4b5c6d7e8f9"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None

_ORG_COLS = ("tamper_score", "license_status", "suspended_at", "deleted_at")


def upgrade():
    conn = op.get_bind()
    if not sa.inspect(conn).has_table("blacklist"):
        op.create_table(
            "blacklist",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("email", sa.String(255), unique=True, nullable=True),
            sa.Column("domain", sa.String(255), nullable=True, index=True),
            sa.Column("cpf_cnpj", sa.String(20), unique=True, nullable=True),
            sa.Column("name", sa.String(255), nullable=True),
            sa.Column("stripe_customer_id", sa.String(100), unique=True, nullable=True),
            sa.Column("reason", sa.Text, nullable=False),
            sa.Column("evidence", JSON, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )
    present = {c["name"] for c in sa.inspect(conn).get_columns("organizations")}
    if [c for c in _ORG_COLS if c not in present]:
        with op.batch_alter_table("organizations") as batch:
            if "tamper_score" not in present:
                batch.add_column(sa.Column("tamper_score", sa.Integer, nullable=False, server_default="0"))
            if "license_status" not in present:
                batch.add_column(sa.Column("license_status", sa.String(20), nullable=False, server_default="active"))
            if "suspended_at" not in present:
                batch.add_column(sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
            if "deleted_at" not in present:
                batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    conn = op.get_bind()
    if sa.inspect(conn).has_table("organizations"):
        present = {c["name"] for c in sa.inspect(conn).get_columns("organizations")}
        drop = [c for c in reversed(_ORG_COLS) if c in present]
        if drop:
            with op.batch_alter_table("organizations") as batch:
                for c in drop:
                    batch.drop_column(c)
    if sa.inspect(conn).has_table("blacklist"):
        op.drop_table("blacklist")
