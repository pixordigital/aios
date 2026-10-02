"""hot-path indexes: composite (org_id, X) and the unindexed inbound-message FK

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-10-01

Every index declared in the schema so far was single-column, while nearly every
hot query is `WHERE org_id = ? AND <x> = ? ORDER BY created_at DESC LIMIT n`.
Postgres then picks the org_id index and heap-filters the rest, which degrades
linearly with tenant size.

conversations.channel_connection_id is the worst case: an unindexed foreign key
on the single hottest write path in a WhatsApp product. Every inbound message
looks up the conversation by channel, so that lookup was a sequential scan of
the whole conversations table.

pending_actions.status had no index at all, so the expiry sweep performed a
full-table scan every cron tick.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, index name, columns)
INDEXES = [
    # inbound WhatsApp message lookup - hottest path in the product
    ("conversations", "ix_conversations_channel_created", ["channel_connection_id", "created_at"]),
    # thread loading
    ("messages", "ix_messages_conversation_created", ["conversation_id", "created_at"]),
    # CRM kanban / pipeline / recency
    ("crm_deals", "ix_crm_deals_org_stage", ["org_id", "stage"]),
    ("crm_deals", "ix_crm_deals_org_pipeline", ["org_id", "pipeline"]),
    ("crm_deals", "ix_crm_deals_org_updated", ["org_id", "updated_at"]),
    # deal history modal
    ("crm_deal_versions", "ix_crm_deal_versions_deal_created", ["deal_id", "created_at"]),
    # monthly quota/analytics sweep
    ("agent_metrics", "ix_agent_metrics_org_hour", ["org_id", "hour"]),
    # approval expiry sweep ran a full scan every tick
    ("pending_actions", "ix_pending_actions_status_created", ["status", "created_at"]),
    # automations list
    ("workflow_runs", "ix_workflow_runs_org_created", ["org_id", "created_at"]),
    # voice webhook lookups by provider call id
    ("voice_recordings", "ix_voice_recordings_org_callsid", ["org_id", "call_sid"]),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    existing_idx = set()
    for tbl in existing_tables:
        try:
            existing_idx.update(i["name"] for i in inspector.get_indexes(tbl))
        except Exception:
            pass

    created = []
    for table, name, cols in INDEXES:
        if table not in existing_tables or name in existing_idx:
            continue
        present = {c["name"] for c in inspector.get_columns(table)}
        if not all(c in present for c in cols):
            # column missing on this database (e.g. older schema) - skip rather
            # than abort the whole chain
            continue
        op.create_index(name, table, cols, unique=False)
        created.append(name)
    if created:
        print(f"[c8d9e0f1a2b3] created {len(created)} indexes")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    for table, name, _cols in reversed(INDEXES):
        if table not in existing_tables:
            continue
        try:
            if any(i["name"] == name for i in inspector.get_indexes(table)):
                op.drop_index(name, table_name=table)
        except Exception:
            pass