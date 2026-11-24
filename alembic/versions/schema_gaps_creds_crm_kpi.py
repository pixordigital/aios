"""Credential rotation/audit/scope/attribution, CRM deal FKs, KPI target schema.

Additive only: legacy rows keep working with NULL links, active/1 credentials,
and their original extra_data mirrors. Backfill copies explicit pointers and
existing KPI JSON into typed rows; it never deletes or rewrites the old keys.

SQLite cannot add a FK with ALTER TABLE. There the columns and indexes exist
and the ORM/model defines the FK; PostgreSQL gets the named FK constraints.

Downgrade drops only objects recorded in _aios_migration_owned_objects by this
revision. Schema provisioned by create_all is never recorded, so rollback
cannot delete pre-existing tables, columns or their data.
"""

import json
import math
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "e1f2a3b4c5d6"
down_revision = "f0e1d2c3b4a5"

text_default = sa.text("'{}'")
text_default_array = sa.text("'[]'")

CREDENTIAL_COLUMNS = (
    ("status", sa.String(20), "active"),
    ("version", sa.Integer, "1"),
    ("rotated_at", sa.DateTime, None),
    ("revoked_at", sa.DateTime, None),
    ("last_used_at", sa.DateTime, None),
    ("created_by", sa.String(36), None),
)
CRM_LINKS = (
    ("account_id", "crm_accounts", "fk_crm_deals_account_id"),
    ("contact_id", "crm_contacts", "fk_crm_deals_contact_id"),
)
OWNED_TABLE = "_aios_migration_owned_objects"


def _inspector():
    return sa.inspect(op.get_bind())


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _columns(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {c["name"] for c in _inspector().get_columns(table)}


def _indexes(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {i["name"] for i in _inspector().get_indexes(table)}


def _fk_names(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {fk["name"] for fk in _inspector().get_foreign_keys(table) if fk.get("name")}


def _unique_names(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {u["name"] for u in _inspector().get_unique_constraints(table) if u.get("name")}


def _create_unique(name: str, table: str, columns: list[str]) -> None:
    if name in _unique_names(table):
        return
    if _is_sqlite():
        with op.batch_alter_table(table) as batch:
            batch.create_unique_constraint(name, columns)
    else:
        op.create_unique_constraint(name, table, columns)


def _add_column(table: str, column: sa.Column) -> bool:
    if column.name in _columns(table):
        return False
    op.add_column(table, column)
    return True


def _create_index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=unique)


def _drop_index(name: str, table: str) -> None:
    if name in _indexes(table):
        op.drop_index(name, table_name=table)


def _drop_column(table: str, name: str) -> None:
    if name not in _columns(table):
        return
    if _is_sqlite():
        with op.batch_alter_table(table) as batch:
            batch.drop_column(name)
    else:
        op.drop_column(table, name)


def _owned_table() -> sa.Table:
    return sa.table(
        OWNED_TABLE,
        sa.column("revision", sa.String(36)),
        sa.column("object_key", sa.String(255)),
    )


def _ensure_owned_table() -> None:
    if _has_table(OWNED_TABLE):
        return
    op.create_table(
        OWNED_TABLE,
        sa.Column("revision", sa.String(36), nullable=False),
        sa.Column("object_key", sa.String(255), nullable=False),
        sa.UniqueConstraint("revision", "object_key", name="uq_migration_owned_object"),
    )


def _owned(rev: str) -> set[str]:
    if not _has_table(OWNED_TABLE):
        return set()
    marker = _owned_table()
    rows = op.get_bind().execute(sa.select(marker.c.object_key).where(marker.c.revision == rev))
    return {row[0] for row in rows}


def _record(rev: str, key: str) -> None:
    _ensure_owned_table()
    if key in _owned(rev):
        return
    op.get_bind().execute(_owned_table().insert().values(revision=rev, object_key=key))


def _drop_owned_table_if_empty() -> None:
    if not _has_table(OWNED_TABLE):
        return
    marker = _owned_table()
    if op.get_bind().execute(sa.select(sa.literal(1)).select_from(marker)).first():
        return
    op.drop_table(OWNED_TABLE)


def _json(raw):
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, (str, bytes)):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}
    return {}


def _dt(raw):
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None)
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc)
            return parsed.replace(tzinfo=None)
        except ValueError:
            return None
    return None


# bool is an int subclass; JSON true/false must not become metric numbers.
def _optional_number(raw):
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, str) and raw.lower() in ("true", "false"):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _optional_integer(raw):
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, str) and raw.lower() in ("true", "false"):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError, OverflowError):
        return None


def _table(name: str, *columns: sa.Column) -> sa.Table:
    return sa.table(name, *columns)


def _backfill_crm_links(conn) -> None:
    """Only explicit same-org extra_data pointers. No name/phone guessing."""
    if not (_has_table("crm_deals") and _has_table("crm_accounts") and _has_table("crm_contacts")):
        return
    deals = _table(
        "crm_deals",
        sa.column("id", sa.String(36)),
        sa.column("org_id", sa.String(36)),
        sa.column("extra_data", sa.JSON),
        sa.column("account_id", sa.String(36)),
        sa.column("contact_id", sa.String(36)),
    )
    accounts = _table("crm_accounts", sa.column("id", sa.String(36)), sa.column("org_id", sa.String(36)))
    contacts = _table("crm_contacts", sa.column("id", sa.String(36)), sa.column("org_id", sa.String(36)))
    account_org = {r.id: r.org_id for r in conn.execute(sa.select(accounts.c.id, accounts.c.org_id))}
    contact_org = {r.id: r.org_id for r in conn.execute(sa.select(contacts.c.id, contacts.c.org_id))}

    rows = sa.select(
        deals.c.id, deals.c.org_id, deals.c.extra_data, deals.c.account_id, deals.c.contact_id
    )
    for deal in conn.execute(rows).mappings():
        extra = _json(deal["extra_data"])
        values = {}
        account_id = extra.get("account_id") if isinstance(extra, dict) else None
        contact_id = extra.get("contact_id") if isinstance(extra, dict) else None
        if deal["account_id"] is None and account_id and account_org.get(account_id) == deal["org_id"]:
            values["account_id"] = account_id
        if deal["contact_id"] is None and contact_id and contact_org.get(contact_id) == deal["org_id"]:
            values["contact_id"] = contact_id
        if values:
            stmt = deals.update().where(deals.c.id == deal["id"])
            for column in values:
                stmt = stmt.where(deals.c[column].is_(None))
            conn.execute(stmt.values(**values))


def _backfill_kpi(conn) -> None:
    """Copy the existing extra_data store; leave the original JSON in place."""
    if not _has_table("organizations"):
        return
    orgs = _table("organizations", sa.column("id", sa.String(36)), sa.column("extra_data", sa.JSON))
    targets = _table(
        "kpi_targets",
        sa.column("id", sa.String(36)),
        sa.column("org_id", sa.String(36)),
        sa.column("metric_key", sa.String(100)),
        sa.column("target_value", sa.Float),
        sa.column("baseline_value", sa.Float),
        sa.column("baseline_window_days", sa.Integer),
        sa.column("evidence", sa.Text),
        sa.column("owner", sa.String(255)),
        sa.column("balancing_metrics", sa.JSON),
        sa.column("status", sa.String(20)),
        sa.column("provenance", sa.JSON),
        sa.column("guardrails", sa.JSON),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    events = _table(
        "kpi_target_events",
        sa.column("id", sa.String(36)),
        sa.column("org_id", sa.String(36)),
        sa.column("target_id", sa.String(36)),
        sa.column("event", sa.String(30)),
        sa.column("metric_key", sa.String(100)),
        sa.column("from_status", sa.String(20)),
        sa.column("to_status", sa.String(20)),
        sa.column("actor_user_id", sa.String(36)),
        sa.column("actor_org_id", sa.String(36)),
        sa.column("at", sa.DateTime),
        sa.column("evidence", sa.Text),
        sa.column("owner", sa.String(255)),
        sa.column("target_value", sa.Float),
        sa.column("baseline_value", sa.Float),
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for org in conn.execute(sa.select(orgs.c.id, orgs.c.extra_data)).mappings():
        extra = _json(org["extra_data"])
        if not isinstance(extra, dict):
            continue
        store = _json(extra.get("kpi_targets"))
        for raw in (store.get("targets") if isinstance(store, dict) else None) or []:
            if not isinstance(raw, dict) or not raw.get("id") or not raw.get("metric_key"):
                continue
            existing = conn.execute(
                sa.select(sa.literal(1)).select_from(targets).where(targets.c.id == raw["id"])
            ).first()
            if existing:
                continue
            target_value = _optional_number(raw.get("target_value"))
            baseline_value = _optional_number(raw.get("baseline_value"))
            window_days = _optional_integer(raw.get("baseline_window_days"))
            if target_value is None or baseline_value is None or window_days is None:
                continue  # no fake metrics: skip targets without real numbers
            conn.execute(targets.insert().values(
                id=str(raw["id"]),
                org_id=org["id"],
                metric_key=str(raw["metric_key"])[:100],
                target_value=target_value,
                baseline_value=baseline_value,
                baseline_window_days=window_days,
                evidence=str(raw.get("evidence") or ""),
                owner=str(raw.get("owner") or "")[:255],
                balancing_metrics=raw.get("balancing_metrics") if isinstance(raw.get("balancing_metrics"), list) else [],
                status=str(raw.get("status") or "active")[:20],
                provenance=_json(raw.get("provenance")),
                guardrails=_json(raw.get("guardrails")),
                created_at=_dt(raw.get("created_at")) or now,
                updated_at=_dt(raw.get("updated_at")) or now,
            ))
        for raw in extra.get("kpi_target_history") or []:
            if not isinstance(raw, dict):
                continue
            event_id = str(raw.get("id") or uuid.uuid4())
            existing = conn.execute(
                sa.select(sa.literal(1)).select_from(events).where(events.c.id == event_id)
            ).first()
            if existing:
                continue
            conn.execute(events.insert().values(
                id=event_id,
                org_id=org["id"],
                target_id=raw.get("target_id") or None,
                event=str(raw.get("event") or "target_updated")[:30],
                metric_key=str(raw.get("metric_key") or "")[:100],
                from_status=raw.get("from_status"),
                to_status=raw.get("to_status"),
                actor_user_id=raw.get("actor_user_id"),
                actor_org_id=raw.get("actor_org_id"),
                at=_dt(raw.get("at")) or now,
                evidence=str(raw.get("evidence") or ""),
                owner=str(raw.get("owner") or "")[:255],
                target_value=_optional_number(raw.get("target_value")),
                baseline_value=_optional_number(raw.get("baseline_value")),
            ))


def upgrade() -> None:
    conn = op.get_bind()
    if _has_table("credentials"):
        for name, col_type, default in CREDENTIAL_COLUMNS:
            if _add_column("credentials", sa.Column(
                name, col_type, nullable=default is None, server_default=default
            )):
                _record(revision, f"column:credentials.{name}")
        if _add_column("credentials", sa.Column(
            "scope", sa.JSON, nullable=False, server_default=text_default
        )):
            _record(revision, "column:credentials.scope")
        _create_index("ix_credentials_status", "credentials", ["status"])

    if not _has_table("credential_events"):
        op.create_table(
            "credential_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("credential_id", sa.String(36), sa.ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False),
            sa.Column("event", sa.String(30), nullable=False, server_default="created"),
            sa.Column("actor_user_id", sa.String(36), nullable=True),
            sa.Column("actor_agent_id", sa.String(36), nullable=True),
            sa.Column("from_version", sa.Integer, nullable=True),
            sa.Column("to_version", sa.Integer, nullable=True),
            sa.Column("details", sa.JSON, nullable=False, server_default=text_default),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )
        _record(revision, "table:credential_events")
    _create_index("ix_credential_events_org_id", "credential_events", ["org_id"])
    _create_index("ix_credential_events_credential_id", "credential_events", ["credential_id"])
    _create_index("ix_credential_events_org_created", "credential_events", ["org_id", "created_at"])
    _create_index("ix_credential_events_cred_created", "credential_events", ["credential_id", "created_at"])

    if not _has_table("credential_scopes"):
        op.create_table(
            "credential_scopes",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("credential_id", sa.String(36), sa.ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False),
            sa.Column("scope_type", sa.String(20), nullable=False),
            sa.Column("scope_id", sa.String(255), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("credential_id", "scope_type", "scope_id", name="uq_credential_scope"),
        )
        _record(revision, "table:credential_scopes")
    _create_unique("uq_credential_scope", "credential_scopes", ["credential_id", "scope_type", "scope_id"])
    _create_index("ix_credential_scopes_org_id", "credential_scopes", ["org_id"])
    _create_index("ix_credential_scopes_credential_id", "credential_scopes", ["credential_id"])

    if not _has_table("usage_attributions"):
        op.create_table(
            "usage_attributions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("date", sa.String(10), nullable=False),
            sa.Column("model", sa.String(200), nullable=True),
            sa.Column("provider", sa.String(100), nullable=True),
            sa.Column("cost_kind", sa.String(20), nullable=False, server_default="internal"),
            sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
            sa.Column("total_tokens", sa.Integer, nullable=False, server_default="0"),
            sa.Column("cost_usd", sa.Float, nullable=False, server_default="0"),
            sa.Column("attribution", sa.JSON, nullable=False, server_default=text_default),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )
        _record(revision, "table:usage_attributions")
    for name, cols in (
        ("ix_usage_attributions_org_id", ["org_id"]),
        ("ix_usage_attributions_date", ["date"]),
        ("ix_usage_attributions_model", ["model"]),
        ("ix_usage_attributions_created_at", ["created_at"]),
        ("ix_usage_attributions_org_date", ["org_id", "date"]),
        ("ix_usage_attributions_org_model", ["org_id", "model"]),
    ):
        _create_index(name, "usage_attributions", cols)

    if _has_table("crm_deals"):
        for column, _target, _fk in CRM_LINKS:
            if _add_column("crm_deals", sa.Column(column, sa.String(36), nullable=True)):
                _record(revision, f"column:crm_deals.{column}")
            _create_index(f"ix_crm_deals_{column}", "crm_deals", [column])
        _backfill_crm_links(conn)
        if not _is_sqlite():
            for column, target, fk_name in CRM_LINKS:
                if fk_name not in _fk_names("crm_deals"):
                    op.create_foreign_key(
                        fk_name, "crm_deals", target, [column], ["id"], ondelete="SET NULL"
                    )
                    _record(revision, f"fk:{fk_name}")

    if not _has_table("kpi_targets"):
        op.create_table(
            "kpi_targets",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("metric_key", sa.String(100), nullable=False),
            sa.Column("target_value", sa.Float, nullable=False, server_default="0"),
            sa.Column("baseline_value", sa.Float, nullable=False, server_default="0"),
            sa.Column("baseline_window_days", sa.Integer, nullable=False, server_default="0"),
            sa.Column("evidence", sa.Text, nullable=False, server_default=""),
            sa.Column("owner", sa.String(255), nullable=False, server_default=""),
            sa.Column("balancing_metrics", sa.JSON, nullable=False, server_default=text_default_array),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("provenance", sa.JSON, nullable=False, server_default=text_default),
            sa.Column("guardrails", sa.JSON, nullable=False, server_default=text_default),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("org_id", "metric_key", name="uq_kpi_target_org_metric"),
        )
        _record(revision, "table:kpi_targets")
    _create_unique("uq_kpi_target_org_metric", "kpi_targets", ["org_id", "metric_key"])
    _create_index("ix_kpi_targets_org_id", "kpi_targets", ["org_id"])
    _create_index("ix_kpi_targets_metric_key", "kpi_targets", ["metric_key"])
    _create_index("ix_kpi_targets_status", "kpi_targets", ["status"])
    _create_index("ix_kpi_targets_created_at", "kpi_targets", ["created_at"])

    if not _has_table("kpi_target_events"):
        op.create_table(
            "kpi_target_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("target_id", sa.String(36), sa.ForeignKey("kpi_targets.id", ondelete="SET NULL"), nullable=True),
            sa.Column("event", sa.String(30), nullable=False),
            sa.Column("metric_key", sa.String(100), nullable=False),
            sa.Column("from_status", sa.String(20), nullable=True),
            sa.Column("to_status", sa.String(20), nullable=True),
            sa.Column("actor_user_id", sa.String(36), nullable=True),
            sa.Column("actor_org_id", sa.String(36), nullable=True),
            sa.Column("at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("evidence", sa.Text, nullable=False, server_default=""),
            sa.Column("owner", sa.String(255), nullable=False, server_default=""),
            sa.Column("target_value", sa.Float, nullable=True),
            sa.Column("baseline_value", sa.Float, nullable=True),
        )
        _record(revision, "table:kpi_target_events")
    for name, cols in (
        ("ix_kpi_target_events_org_id", ["org_id"]),
        ("ix_kpi_target_events_target_id", ["target_id"]),
        ("ix_kpi_target_events_metric_key", ["metric_key"]),
        ("ix_kpi_target_events_org_at", ["org_id", "at"]),
    ):
        _create_index(name, "kpi_target_events", cols)
    _backfill_kpi(conn)


def downgrade() -> None:
    owned = _owned(revision)
    if not owned:  # no marker: this revision created nothing (or already rolled back)
        return

    if not _is_sqlite():
        for _column, _target, fk_name in CRM_LINKS:
            if f"fk:{fk_name}" in owned and fk_name in _fk_names("crm_deals"):
                op.drop_constraint(fk_name, "crm_deals", type_="foreignkey")

    for column, _target, _fk in CRM_LINKS:
        if f"column:crm_deals.{column}" in owned:
            _drop_index(f"ix_crm_deals_{column}", "crm_deals")
            _drop_column("crm_deals", column)

    if "column:credentials.status" in owned:
        _drop_index("ix_credentials_status", "credentials")
    for name, _col_type, _default in reversed(CREDENTIAL_COLUMNS):
        if f"column:credentials.{name}" in owned:
            _drop_column("credentials", name)
    if "column:credentials.scope" in owned:
        _drop_column("credentials", "scope")

    for table in (
        "kpi_target_events", "kpi_targets", "usage_attributions",
        "credential_scopes", "credential_events",
    ):
        if f"table:{table}" in owned and _has_table(table):
            op.drop_table(table)

    marker = _owned_table()
    op.get_bind().execute(marker.delete().where(marker.c.revision == revision))
    _drop_owned_table_if_empty()
