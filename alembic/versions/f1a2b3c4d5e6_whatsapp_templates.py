"""whatsapp_connections + whatsapp_templates: Meta Cloud API template studio

Revision ID: f1a2b3c4d5e6
Revises: z6a7b8c9d0e1
Create Date: 2026-10-02

Templates are assets of a WhatsApp Business Account, not of this app, so waba_id
is stored on the template row and every query must scope to the org's own
connection. Templates are not portable between WABAs.

The unique constraint on (org_id, waba_id, name, language) mirrors Meta's own
rule that a template name is unique within a WABA per language. It is created
only after collapsing existing duplicates so the migration cannot fail on a
database that already holds them.

Guarded/idempotent throughout: init_db() runs create_all on every startup, so
these tables may already exist on a deployed database.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "z6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONN = "whatsapp_connections"
TMPL = "whatsapp_templates"


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _columns(table: str) -> set:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _has_unique(table: str, name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return False
    for u in insp.get_unique_constraints(table):
        if u.get("name") == name:
            return True
    return any(i.get("name") == name for i in insp.get_indexes(table))


def _index_exists(name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    for tbl in insp.get_table_names():
        for i in insp.get_indexes(tbl):
            if i.get("name") == name:
                return True
    return False


def upgrade() -> None:
    if not _has_table(CONN):
        op.create_table(
            CONN,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("waba_id", sa.String(64), nullable=False),
            sa.Column("phone_number_id", sa.String(64), nullable=True),
            sa.Column("business_id", sa.String(64), nullable=True),
            sa.Column("display_name", sa.String(255), server_default=""),
            sa.Column("access_token_enc", sa.Text(), server_default=""),
            sa.Column("status", sa.String(30), server_default="unverified"),
            sa.Column("last_verified_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index(f"ix_{CONN}_org_id", CONN, ["org_id"])
        op.create_index(f"ix_{CONN}_waba_id", CONN, ["waba_id"])

    if not _has_table(TMPL):
        op.create_table(
            TMPL,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("connection_id", sa.String(36), nullable=True),
            sa.Column("waba_id", sa.String(64), server_default=""),
            sa.Column("meta_template_id", sa.String(64), nullable=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("language", sa.String(16), server_default="pt_BR"),
            sa.Column("category", sa.String(30), server_default="UTILITY"),
            sa.Column("sub_category", sa.String(80), nullable=True),
            sa.Column("header_text", sa.Text(), server_default=""),
            sa.Column("body", sa.Text(), server_default=""),
            sa.Column("footer", sa.Text(), server_default=""),
            sa.Column("examples_json", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(30), server_default="DRAFT"),
            sa.Column("rejected_reason", sa.String(64), nullable=True),
            sa.Column("rejection_note", sa.Text(), server_default=""),
            sa.Column("quality_score", sa.String(30), nullable=True),
            sa.Column("message_send_ttl_seconds", sa.Integer(), nullable=True),
            sa.Column("submitted_by", sa.String(36), nullable=True),
            sa.Column("submitted_at", sa.DateTime(), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(), nullable=True),
            # server_default so this succeeds on a populated table
            sa.Column("edit_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_edit_at", sa.DateTime(), nullable=True),
            sa.Column("local_notes", sa.Text(), server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        for col in ("org_id", "waba_id", "meta_template_id", "status", "connection_id"):
            op.create_index(f"ix_{TMPL}_{col}", TMPL, [col])

    # Collapse any pre-existing duplicates before adding the constraint, or the
    # create fails on exactly the databases that have them.
    op.execute(
        sa.text(
            f"""
            DELETE FROM {TMPL}
            WHERE id NOT IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY org_id, waba_id, name, language
                        ORDER BY created_at DESC, id DESC
                    ) AS rn FROM {TMPL}
                ) ranked WHERE ranked.rn = 1
            )
            """
        )
    )

    for name, cols in (
        ("uq_whatsapp_conn_org_waba", [CONN, "org_id", "waba_id"]),
        ("uq_watpl_org_waba_name_lang", [TMPL, "org_id", "waba_id", "name", "language"]),
    ):
        table = CONN if name.startswith("uq_whatsapp_conn") else TMPL
        if not _has_unique(table, name):
            with op.batch_alter_table(table, schema=None) as batch_op:
                batch_op.create_unique_constraint(name, cols)

    if "webhook_secret_enc" not in _columns(CONN):
        op.add_column(CONN, sa.Column("webhook_secret_enc", sa.Text(), server_default=""))

    for name, table, cols in (
        ("ix_whatsapp_templates_org_status", TMPL, ["org_id", "status"]),
        ("ix_whatsapp_templates_org_name", TMPL, ["org_id", "name"]),
    ):
        if not _index_exists(name):
            op.create_index(name, table, cols)


def downgrade() -> None:
    if _index_exists("ix_whatsapp_templates_org_status"):
        op.drop_index("ix_whatsapp_templates_org_status", table_name=TMPL)
    if _index_exists("ix_whatsapp_templates_org_name"):
        op.drop_index("ix_whatsapp_templates_org_name", table_name=TMPL)
    if _has_table(TMPL) and _has_unique(TMPL, "uq_watpl_org_waba_name_lang"):
        with op.batch_alter_table(TMPL, schema=None) as batch_op:
            batch_op.drop_constraint("uq_watpl_org_waba_name_lang", type_="unique")
    if _has_table(CONN) and _has_unique(CONN, "uq_whatsapp_conn_org_waba"):
        with op.batch_alter_table(CONN, schema=None) as batch_op:
            batch_op.drop_constraint("uq_whatsapp_conn_org_waba", type_="unique")
    for t in (TMPL, CONN):
        if _has_table(t):
            op.drop_table(t)