"""Schema gaps: migration round-trip on SQLite + model constraints.

No live DB, no provider, no conftest fixtures. The migration is exercised on a
temp SQLite file with a hand-built legacy schema so upgrade/downgrade is testable
without the full Alembic history or production data.
"""

import importlib.util
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aios.db import models
from aios.db.engine import Base

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "alembic" / "versions" / "schema_gaps_creds_crm_kpi.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("_schema_gaps_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def model_engine():
    # crm_intelligence owns Account/Contact mappers referenced by CrmDeal FKs.
    import aios.core.crm_intelligence  # noqa: F401

    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _indexes(inspector, table):
    return {i["name"] for i in inspector.get_indexes(table)}


def test_revision_is_a_single_new_head():
    migration = _load_migration()
    assert migration.revision == "e1f2a3b4c5d6"
    assert migration.down_revision == "f0e1d2c3b4a5"


def test_credential_model_carries_rotation_audit_scope_and_attribution(model_engine):
    inspector = sa.inspect(model_engine)
    credential_cols = {c["name"] for c in inspector.get_columns("credentials")}
    assert {"status", "version", "rotated_at", "revoked_at", "last_used_at", "created_by", "scope"} <= credential_cols

    event_fks = inspector.get_foreign_keys("credential_events")
    assert any(
        fk["referred_table"] == "credentials" and fk["options"].get("ondelete") == "CASCADE"
        for fk in event_fks
    )
    unique = {c["name"] for c in inspector.get_unique_constraints("credential_scopes")}
    assert "uq_credential_scope" in unique
    assert "ix_usage_attributions_org_date" in _indexes(inspector, "usage_attributions")

    with Session(model_engine) as session:
        org = models.Organization(name="Org", slug="org")
        session.add(org)
        session.flush()
        cred = models.Credential(org_id=org.id, name="hubspot", cred_type="bearer", data_enc="enc")
        session.add(cred)
        session.flush()
        session.add(models.CredentialEvent(org_id=org.id, credential_id=cred.id, event="created", actor_user_id="u1"))
        session.add(models.UsageAttribution(org_id=org.id, date="2026-11-24", model="openai/gpt", attribution={"path": "run_stream"}))
        session.commit()

        saved = session.get(models.Credential, cred.id)
        assert saved.status == "active"
        assert saved.version == 1
        assert session.scalar(sa.select(sa.func.count()).select_from(models.CredentialEvent)) == 1
        assert session.scalar(sa.select(sa.func.count()).select_from(models.UsageAttribution)) == 1


def test_credential_scope_is_unique(model_engine):
    with Session(model_engine) as session:
        org = models.Organization(name="Org", slug="org")
        session.add(org)
        session.flush()
        cred = models.Credential(org_id=org.id, name="key", cred_type="bearer")
        session.add(cred)
        session.flush()
        session.add(models.CredentialScope(org_id=org.id, credential_id=cred.id, scope_type="agent", scope_id="a1"))
        session.commit()
        session.add(models.CredentialScope(org_id=org.id, credential_id=cred.id, scope_type="agent", scope_id="a1"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_crm_deal_links_are_nullable_but_enforced(model_engine):
    inspector = sa.inspect(model_engine)
    fks = inspector.get_foreign_keys("crm_deals")
    referred = {fk["referred_table"] for fk in fks}
    assert {"crm_accounts", "crm_contacts"} <= referred

    with Session(model_engine) as session:
        org = models.Organization(name="Org", slug="org")
        session.add(org)
        session.flush()
        deal = models.CrmDeal(org_id=org.id, lead_name="Ana")
        session.add(deal)
        session.commit()  # NULL links must not break legacy rows

        deal.account_id = "missing-account"
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_kpi_target_schema_enforces_one_target_per_metric(model_engine):
    with Session(model_engine) as session:
        org = models.Organization(name="Org", slug="org")
        session.add(org)
        session.flush()
        target = models.KpiTarget(
            org_id=org.id,
            metric_key="crm.win_rate",
            target_value=0.7,
            baseline_value=0.6,
            baseline_window_days=30,
            evidence="query",
            owner="sales",
        )
        session.add(target)
        session.flush()
        session.add(models.KpiTargetEvent(
            org_id=org.id, target_id=target.id, event="target_created", metric_key=target.metric_key
        ))
        session.commit()
        session.add(models.KpiTarget(org_id=org.id, metric_key="crm.win_rate"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def _legacy_schema(conn):
    conn.execute(sa.text("""
        CREATE TABLE organizations (id VARCHAR(36) PRIMARY KEY, extra_data JSON)
    """))
    conn.execute(sa.text("""
        CREATE TABLE credentials (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36), name VARCHAR(255),
            cred_type VARCHAR(50), data_enc TEXT, extra_data JSON
        )
    """))
    conn.execute(sa.text("""
        CREATE TABLE crm_accounts (id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36), name VARCHAR(255))
    """))
    conn.execute(sa.text("""
        CREATE TABLE crm_contacts (id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36), name VARCHAR(255))
    """))
    conn.execute(sa.text("""
        CREATE TABLE crm_deals (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36), lead_name VARCHAR(255),
            stage VARCHAR(30), extra_data JSON
        )
    """))
    conn.execute(sa.text("CREATE TABLE usage_records (id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36), date VARCHAR(10))"))


def _seed_legacy(conn):
    kpi_extra = {
        "kpi_targets": {
            "version": 1,
            "targets": [{
                "id": "kt-1",
                "metric_key": "crm.win_rate",
                "target_value": 0.7,
                "baseline_value": 0.6,
                "baseline_window_days": 30,
                "evidence": "crm query",
                "owner": "sales",
                "balancing_metrics": ["crm.cycle_days"],
                "status": "active",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-02T00:00:00+00:00",
                "provenance": {"actor_user_id": "u1"},
                "guardrails": {"no_fake_metrics": True},
            }],
        },
        "kpi_target_history": [{
            "id": "k ev-1",
            "event": "target_created",
            "metric_key": "crm.win_rate",
            "target_id": "kt-1",
            "from_status": None,
            "to_status": "active",
            "actor_user_id": "u1",
            "actor_org_id": "org-1",
            "at": "2026-01-01T00:00:00+00:00",
            "evidence": "crm query",
            "owner": "sales",
            "target_value": 0.7,
            "baseline_value": 0.6,
        }],
    }
    conn.execute(sa.text("INSERT INTO organizations (id, extra_data) VALUES (:id, :extra)"), {
        "id": "org-1", "extra": json.dumps(kpi_extra),
    })
    conn.execute(sa.text("INSERT INTO organizations (id, extra_data) VALUES (:id, :extra)"), {
        "id": "org-2", "extra": "{}",
    })
    conn.execute(sa.text("""
        INSERT INTO credentials (id, org_id, name, cred_type, data_enc, extra_data)
        VALUES (:id, :org, 'key', 'bearer', 'enc', '{}')
    """), {"id": "cred-1", "org": "org-1"})
    for acc_id, org_id in (("acc-1", "org-1"), ("acc-other", "org-2")):
        conn.execute(sa.text("INSERT INTO crm_accounts (id, org_id, name) VALUES (:id, :org, 'A')"), {
            "id": acc_id, "org": org_id,
        })
    for con_id, org_id in (("con-1", "org-1"),):
        conn.execute(sa.text("INSERT INTO crm_contacts (id, org_id, name) VALUES (:id, :org, 'C')"), {
            "id": con_id, "org": org_id,
        })
    deals = (
        ("deal-1", "org-1", {"account_id": "acc-1", "contact_id": "con-1"}),
        ("deal-2", "org-1", {"account_id": "acc-other", "contact_id": "missing"}),
        ("deal-3", "org-2", {"account_id": "acc-other"}),
        ("deal-4", "org-1", {}),
    )
    for deal_id, org_id, extra in deals:
        conn.execute(sa.text("""
            INSERT INTO crm_deals (id, org_id, lead_name, stage, extra_data)
            VALUES (:id, :org, 'L', 'mql', :extra)
        """), {"id": deal_id, "org": org_id, "extra": json.dumps(extra)})
    return kpi_extra


def test_migration_upgrade_backfill_idempotence_and_downgrade(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")

    with engine.begin() as conn:
        _legacy_schema(conn)
        original_kpi_extra = _seed_legacy(conn)
        context = MigrationContext.configure(conn, opts={"render_as_batch": True})

        with Operations.context(context):
            migration.upgrade()

        inspector = sa.inspect(conn)
        tables = set(inspector.get_table_names())
        assert {"credential_events", "credential_scopes", "usage_attributions", "kpi_targets", "kpi_target_events"} <= tables
        assert {"status", "version", "scope"} <= {c["name"] for c in inspector.get_columns("credentials")}
        assert {"account_id", "contact_id"} <= {c["name"] for c in inspector.get_columns("crm_deals")}

        row = conn.execute(sa.text("SELECT status, version, scope FROM credentials WHERE id='cred-1'")).one()
        assert row.status == "active" and row.version == 1 and json.loads(row.scope) == {}

        links = {
            row.id: (row.account_id, row.contact_id)
            for row in conn.execute(sa.text("SELECT id, account_id, contact_id FROM crm_deals"))
        }
        assert links["deal-1"] == ("acc-1", "con-1")
        assert links["deal-2"] == (None, None)
        assert links["deal-3"] == ("acc-other", None)
        assert links["deal-4"] == (None, None)

        target = conn.execute(sa.text("SELECT * FROM kpi_targets WHERE id='kt-1'")).mappings().one()
        assert target["org_id"] == "org-1"
        assert target["metric_key"] == "crm.win_rate"
        assert target["target_value"] == 0.7
        assert target["baseline_window_days"] == 30
        assert target["status"] == "active"
        assert json.loads(target["balancing_metrics"]) == ["crm.cycle_days"]
        assert conn.execute(sa.text("SELECT count(*) FROM kpi_target_events")).scalar_one() == 1

        # Backfill copies; it never rewrites the legacy store.
        stored = conn.execute(sa.text("SELECT extra_data FROM organizations WHERE id='org-1'")).scalar_one()
        assert json.loads(stored) == original_kpi_extra

        with Operations.context(context):
            migration.upgrade()  # repeat must not duplicate rows or fail
        assert conn.execute(sa.text("SELECT count(*) FROM kpi_targets")).scalar_one() == 1
        assert conn.execute(sa.text("SELECT count(*) FROM kpi_target_events")).scalar_one() == 1

        with Operations.context(context):
            migration.downgrade()

        inspector = sa.inspect(conn)
        tables = set(inspector.get_table_names())
        assert not {"credential_events", "credential_scopes", "usage_attributions", "kpi_targets", "kpi_target_events"} & tables
        assert "status" not in {c["name"] for c in inspector.get_columns("credentials")}
        assert "account_id" not in {c["name"] for c in inspector.get_columns("crm_deals")}
        assert conn.execute(sa.text("SELECT count(*) FROM crm_deals")).scalar_one() == 4
        stored = conn.execute(sa.text("SELECT extra_data FROM organizations WHERE id='org-1'")).scalar_one()
        assert json.loads(stored) == original_kpi_extra

    engine.dispose()
