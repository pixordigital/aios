"""blacklist + tamper columns — prevenção fraude re-cadastro"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "h4b5c6d7e8f9"
down_revision = "g3a4b5c6d7e8"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "blacklist",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=True),
        sa.Column("domain", sa.String(255), nullable=True, index=True),
        sa.Column("cpf_cnpj", sa.String(20), unique=True, nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("stripe_customer_id", sa.String(100), unique=True, nullable=True),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("evidence", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_blacklist_domain", "blacklist", ["domain"])
    # tamper tracking on organizations (Control Plane source of truth)
    with op.batch_alter_table("organizations") as batch:
        batch.add_column(sa.Column("tamper_score", sa.Integer, nullable=False, server_default="0"))
        batch.add_column(sa.Column("license_status", sa.String(20), nullable=False, server_default="active"))
        batch.add_column(sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

def downgrade():
    with op.batch_alter_table("organizations") as batch:
        batch.drop_column("deleted_at")
        batch.drop_column("suspended_at")
        batch.drop_column("license_status")
        batch.drop_column("tamper_score")
    op.drop_index("ix_blacklist_domain", table_name="blacklist")
    op.drop_table("blacklist")
