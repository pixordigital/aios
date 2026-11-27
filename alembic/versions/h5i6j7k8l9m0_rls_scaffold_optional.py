"""Optional Postgres RLS scaffold for key org-scoped tables.

Fail-safe by default: no-op unless AIOS_APPLY_RLS_SCAFFOLD=1 at migration time.
Postgres only; SQLite/dev unaffected.

This is a scaffold, not full tenant isolation. App must set
`SET LOCAL app.current_org_id = '<org_id>'` per transaction/request before
enabling enforcement. Review policies, coverage, and role ownership before
production use.
"""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa

revision = "h5i6j7k8l9m0"
down_revision = "g4h5i6j7k8l9"
branch_labels = None
depends_on = None

# Key org-scoped tables with direct org_id column. Extend deliberately.
ORG_SCOPED_TABLES = [
    "users",
    "agents",
    "conversations",
    "messages",
    "audit_logs",
    "pending_actions",
    "credentials",
    "usage_records",
    "memories",
    "channel_connections",
    "whatsapp_connections",
    "whatsapp_templates",
    "crm_deals",
    "workflows",
    "workflow_runs",
    "agent_packs",
    "agent_pack_versions",
    "agent_pack_activations",
    "owner_notifications",
]


def _enabled() -> bool:
    return os.getenv("AIOS_APPLY_RLS_SCAFFOLD", "").strip() == "1"


def _existing_tables(bind) -> set[str]:
    insp = sa.inspect(bind)
    return set(insp.get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if not _enabled():
        # Scaffold only. No-op keeps sqlite/dev/default deploy safe.
        print("AIOS RLS scaffold skipped (set AIOS_APPLY_RLS_SCAFFOLD=1 to apply)")
        return

    tables = [t for t in ORG_SCOPED_TABLES if t in _existing_tables(bind)]
    for table in tables:
        op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'DROP POLICY IF EXISTS "{table}_org_isolation" ON "{table}"'))
        op.execute(
            sa.text(
                f"""
                CREATE POLICY "{table}_org_isolation" ON "{table}"
                USING (org_id::text = current_setting('app.current_org_id', true))
                WITH CHECK (org_id::text = current_setting('app.current_org_id', true))
                """
            )
        )
    print(f"AIOS RLS scaffold applied to {len(tables)} table(s)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    if not _enabled():
        print("AIOS RLS scaffold downgrade skipped (set AIOS_APPLY_RLS_SCAFFOLD=1)")
        return
    tables = [t for t in ORG_SCOPED_TABLES if t in _existing_tables(bind)]
    for table in tables:
        op.execute(sa.text(f'DROP POLICY IF EXISTS "{table}_org_isolation" ON "{table}"'))
        op.execute(sa.text(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY'))
        op.execute(sa.text(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY'))
    print(f"AIOS RLS scaffold removed from {len(tables)} table(s)")
