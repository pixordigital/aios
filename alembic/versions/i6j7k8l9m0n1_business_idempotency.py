"""durable business execution idempotency records

Revision ID: i6j7k8l9m0n1
Revises: h5i6j7k8l9m0
Create Date: 2026-11-27
"""

from alembic import op
import sqlalchemy as sa


revision = "i6j7k8l9m0n1"
down_revision = "h5i6j7k8l9m0"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_index(table: str, name: str) -> bool:
    if not _has_table(table):
        return False
    return any(i["name"] == name for i in sa.inspect(op.get_bind()).get_indexes(table))


def upgrade():
    if not _has_table("business_idempotency_records"):
        op.create_table(
            "business_idempotency_records",
            sa.Column("scope", sa.String(64), primary_key=True, nullable=False),
            sa.Column("idempotency_key", sa.String(128), primary_key=True, nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="processing"),
            sa.Column("adapter", sa.String(64), nullable=False, server_default=""),
            sa.Column("action", sa.String(128), nullable=False, server_default=""),
            sa.Column("org_id", sa.String(64), nullable=True),
            sa.Column("result_json", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("scope", "idempotency_key", name="uq_business_idempotency_scope_key"),
        )
    if not _has_index("business_idempotency_records", "ix_business_idempotency_records_org_id"):
        op.create_index(
            "ix_business_idempotency_records_org_id",
            "business_idempotency_records",
            ["org_id"],
        )


def downgrade():
    if _has_table("business_idempotency_records"):
        if _has_index("business_idempotency_records", "ix_business_idempotency_records_org_id"):
            op.drop_index("ix_business_idempotency_records_org_id", table_name="business_idempotency_records")
        op.drop_table("business_idempotency_records")
