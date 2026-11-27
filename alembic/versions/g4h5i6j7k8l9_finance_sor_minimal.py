"""minimal finance/legal system-of-record tables

Revision ID: g4h5i6j7k8l9
Revises: f3a4b5c6d7e8
Create Date: 2026-11-27
"""

from alembic import op
import sqlalchemy as sa


revision = "g4h5i6j7k8l9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_index(table: str, name: str) -> bool:
    if not _has_table(table):
        return False
    return any(i["name"] == name for i in sa.inspect(op.get_bind()).get_indexes(table))


def upgrade():
    if not _has_table("finance_contracts"):
        op.create_table(
            "finance_contracts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("external_id", sa.String(128), nullable=True, index=True),
            sa.Column("contract_number", sa.String(64), nullable=True),
            sa.Column("customer_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("customer_ref", sa.String(128), nullable=True, index=True),
            sa.Column("account_id", sa.String(36), sa.ForeignKey("crm_accounts.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("contact_id", sa.String(36), sa.ForeignKey("crm_contacts.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("deal_id", sa.String(36), sa.ForeignKey("crm_deals.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="draft", index=True),
            sa.Column("currency", sa.String(10), nullable=False, server_default="BRL"),
            sa.Column("effective_at", sa.DateTime(), nullable=True),
            sa.Column("ends_at", sa.DateTime(), nullable=True),
            sa.Column("current_version_id", sa.String(36), nullable=True, index=True),
            sa.Column("idempotency_key", sa.String(128), nullable=True),
            sa.Column("extra_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("org_id", "external_id", name="uq_finance_contracts_org_external_id"),
            sa.UniqueConstraint("org_id", "idempotency_key", name="uq_finance_contracts_org_idempotency_key"),
        )
    if not _has_index("finance_contracts", "ix_finance_contracts_org_status"):
        op.create_index("ix_finance_contracts_org_status", "finance_contracts", ["org_id", "status"])

    if not _has_table("finance_contract_versions"):
        op.create_table(
            "finance_contract_versions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("contract_id", sa.String(36), sa.ForeignKey("finance_contracts.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(30), nullable=False, server_default="draft", index=True),
            sa.Column("title", sa.String(255), nullable=False, server_default=""),
            sa.Column("terms", sa.Text(), nullable=False, server_default=""),
            sa.Column("amount_minor", sa.BigInteger(), nullable=True),
            sa.Column("currency", sa.String(10), nullable=False, server_default="BRL"),
            sa.Column("effective_at", sa.DateTime(), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("approved_by", sa.String(36), nullable=True),
            sa.Column("source", sa.String(50), nullable=False, server_default="manual"),
            sa.Column("idempotency_key", sa.String(128), nullable=True),
            sa.Column("content_hash", sa.String(64), nullable=True),
            sa.Column("extra_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("contract_id", "version_number", name="uq_finance_contract_versions_contract_version"),
            sa.UniqueConstraint("org_id", "idempotency_key", name="uq_finance_contract_versions_org_idempotency_key"),
        )
    if not _has_index("finance_contract_versions", "ix_finance_contract_versions_org_contract"):
        op.create_index("ix_finance_contract_versions_org_contract", "finance_contract_versions", ["org_id", "contract_id"])

    if not _has_table("finance_invoices"):
        op.create_table(
            "finance_invoices",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("external_id", sa.String(128), nullable=True, index=True),
            sa.Column("invoice_number", sa.String(64), nullable=True),
            sa.Column("contract_id", sa.String(36), sa.ForeignKey("finance_contracts.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("contract_version_id", sa.String(36), sa.ForeignKey("finance_contract_versions.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("account_id", sa.String(36), sa.ForeignKey("crm_accounts.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("contact_id", sa.String(36), sa.ForeignKey("crm_contacts.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="draft", index=True),
            sa.Column("currency", sa.String(10), nullable=False, server_default="BRL"),
            sa.Column("subtotal_minor", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("tax_minor", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("total_minor", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("amount_due_minor", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("issued_at", sa.DateTime(), nullable=True),
            sa.Column("due_at", sa.DateTime(), nullable=True),
            sa.Column("paid_at", sa.DateTime(), nullable=True),
            sa.Column("idempotency_key", sa.String(128), nullable=True),
            sa.Column("extra_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("org_id", "external_id", name="uq_finance_invoices_org_external_id"),
            sa.UniqueConstraint("org_id", "idempotency_key", name="uq_finance_invoices_org_idempotency_key"),
        )
    if not _has_index("finance_invoices", "ix_finance_invoices_org_status_due"):
        op.create_index("ix_finance_invoices_org_status_due", "finance_invoices", ["org_id", "status", "due_at"])

    if not _has_table("finance_invoice_lines"):
        op.create_table(
            "finance_invoice_lines",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("invoice_id", sa.String(36), sa.ForeignKey("finance_invoices.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("line_no", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("quantity", sa.Numeric(18, 6), nullable=False, server_default="1"),
            sa.Column("unit_amount_minor", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("line_amount_minor", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("tax_minor", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default="BRL"),
            sa.Column("external_id", sa.String(128), nullable=True),
            sa.Column("idempotency_key", sa.String(128), nullable=True),
            sa.Column("extra_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("invoice_id", "line_no", name="uq_finance_invoice_lines_invoice_line_no"),
            sa.UniqueConstraint("org_id", "idempotency_key", name="uq_finance_invoice_lines_org_idempotency_key"),
        )
    if not _has_index("finance_invoice_lines", "ix_finance_invoice_lines_org_invoice"):
        op.create_index("ix_finance_invoice_lines_org_invoice", "finance_invoice_lines", ["org_id", "invoice_id"])

    if not _has_table("finance_payments"):
        op.create_table(
            "finance_payments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("external_id", sa.String(128), nullable=True, index=True),
            sa.Column("invoice_id", sa.String(36), sa.ForeignKey("finance_invoices.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("provider", sa.String(50), nullable=False, server_default="manual", index=True),
            sa.Column("provider_payment_id", sa.String(128), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="pending", index=True),
            sa.Column("amount_minor", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default="BRL"),
            sa.Column("paid_at", sa.DateTime(), nullable=True),
            sa.Column("idempotency_key", sa.String(128), nullable=True),
            sa.Column("extra_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("org_id", "external_id", name="uq_finance_payments_org_external_id"),
            sa.UniqueConstraint("org_id", "idempotency_key", name="uq_finance_payments_org_idempotency_key"),
            sa.UniqueConstraint("org_id", "provider", "provider_payment_id", name="uq_finance_payments_org_provider_payment_id"),
        )
    if not _has_index("finance_payments", "ix_finance_payments_org_status"):
        op.create_index("ix_finance_payments_org_status", "finance_payments", ["org_id", "status"])

    if not _has_table("finance_refunds"):
        op.create_table(
            "finance_refunds",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("external_id", sa.String(128), nullable=True, index=True),
            sa.Column("payment_id", sa.String(36), sa.ForeignKey("finance_payments.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("invoice_id", sa.String(36), sa.ForeignKey("finance_invoices.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("provider", sa.String(50), nullable=False, server_default="manual", index=True),
            sa.Column("provider_refund_id", sa.String(128), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="pending", index=True),
            sa.Column("amount_minor", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default="BRL"),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("refunded_at", sa.DateTime(), nullable=True),
            sa.Column("idempotency_key", sa.String(128), nullable=True),
            sa.Column("extra_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("org_id", "external_id", name="uq_finance_refunds_org_external_id"),
            sa.UniqueConstraint("org_id", "idempotency_key", name="uq_finance_refunds_org_idempotency_key"),
            sa.UniqueConstraint("org_id", "provider", "provider_refund_id", name="uq_finance_refunds_org_provider_refund_id"),
        )
    if not _has_index("finance_refunds", "ix_finance_refunds_org_status"):
        op.create_index("ix_finance_refunds_org_status", "finance_refunds", ["org_id", "status"])

    if not _has_table("finance_ledger_entries"):
        op.create_table(
            "finance_ledger_entries",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("external_id", sa.String(128), nullable=True, index=True),
            sa.Column("entry_type", sa.String(40), nullable=False, index=True),
            sa.Column("direction", sa.String(10), nullable=False, server_default="debit"),
            sa.Column("account_code", sa.String(64), nullable=False, server_default=""),
            sa.Column("amount_minor", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default="BRL"),
            sa.Column("occurred_at", sa.DateTime(), nullable=False, index=True),
            sa.Column("contract_id", sa.String(36), sa.ForeignKey("finance_contracts.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("invoice_id", sa.String(36), sa.ForeignKey("finance_invoices.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("payment_id", sa.String(36), sa.ForeignKey("finance_payments.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("refund_id", sa.String(36), sa.ForeignKey("finance_refunds.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("reverses_entry_id", sa.String(36), sa.ForeignKey("finance_ledger_entries.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("source_system", sa.String(50), nullable=False, server_default="aios"),
            sa.Column("source_ref", sa.String(128), nullable=True),
            sa.Column("idempotency_key", sa.String(128), nullable=True),
            sa.Column("posted_at", sa.DateTime(), nullable=True),
            sa.Column("extra_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("org_id", "external_id", name="uq_finance_ledger_entries_org_external_id"),
            sa.UniqueConstraint("org_id", "idempotency_key", name="uq_finance_ledger_entries_org_idempotency_key"),
        )
    if not _has_index("finance_ledger_entries", "ix_finance_ledger_entries_org_occurred"):
        op.create_index("ix_finance_ledger_entries_org_occurred", "finance_ledger_entries", ["org_id", "occurred_at"])
    if not _has_index("finance_ledger_entries", "ix_finance_ledger_entries_org_type"):
        op.create_index("ix_finance_ledger_entries_org_type", "finance_ledger_entries", ["org_id", "entry_type"])


def downgrade():
    for t in (
        "finance_ledger_entries",
        "finance_refunds",
        "finance_payments",
        "finance_invoice_lines",
        "finance_invoices",
        "finance_contract_versions",
        "finance_contracts",
    ):
        if _has_table(t):
            op.drop_table(t)
