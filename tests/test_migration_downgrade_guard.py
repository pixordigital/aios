"""Migration provenance and backfill guards on temp SQLite databases only.

No live DB, no network, no prod data. A pre-created schema (as init_db's
create_all produces) must survive downgrade; backfills must not invent metrics
or overwrite authoritative pointers.
"""

import importlib.util
import json
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _load(name, module_name):
    spec = importlib.util.spec_from_file_location(module_name, VERSIONS / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _context(conn):
    return MigrationContext.configure(conn, opts={"render_as_batch": True})


def _legacy_schema(conn, *, precreated: bool = False):
    cred_cols = ""
    deal_cols = ""
    if precreated:
        cred_cols = (
            ", status VARCHAR(20), version INTEGER, rotated_at DATETIME, revoked_at DATETIME, "
            "last_used_at DATETIME, created_by VARCHAR(36), scope JSON"
        )
        deal_cols = ", account_id VARCHAR(36), contact_id VARCHAR(36)"
    conn.execute(sa.text("CREATE TABLE organizations (id VARCHAR(36) PRIMARY KEY, extra_data JSON)"))
    conn.execute(sa.text(
        "CREATE TABLE credentials (id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36), name VARCHAR(255), "
        f"cred_type VARCHAR(50), data_enc TEXT, extra_data JSON{cred_cols})"
    ))
    conn.execute(sa.text("CREATE TABLE crm_accounts (id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36), name VARCHAR(255))"))
    conn.execute(sa.text("CREATE TABLE crm_contacts (id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36), name VARCHAR(255))"))
    conn.execute(sa.text(
        "CREATE TABLE crm_deals (id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36), lead_name VARCHAR(255), "
        f"stage VARCHAR(30), extra_data JSON{deal_cols})"
    ))
    if precreated:
        conn.execute(sa.text(
            "CREATE TABLE credential_events (id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36), "
            "credential_id VARCHAR(36), event VARCHAR(30), details JSON, created_at DATETIME)"
        ))
        # Deliberately missing uq_credential_scope / uq_kpi_target_org_metric:
        # a partial upgrade must add them instead of silently advancing.
        conn.execute(sa.text(
            "CREATE TABLE credential_scopes (id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36), "
            "credential_id VARCHAR(36), scope_type VARCHAR(20), scope_id VARCHAR(255), created_at DATETIME)"
        ))
        conn.execute(sa.text(
            "CREATE TABLE usage_attributions (id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36), date VARCHAR(10), "
            "model VARCHAR(200), provider VARCHAR(100), cost_kind VARCHAR(20), input_tokens INTEGER, "
            "output_tokens INTEGER, total_tokens INTEGER, cost_usd FLOAT, attribution JSON, created_at DATETIME)"
        ))
        conn.execute(sa.text(
            "CREATE TABLE kpi_targets (id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36), metric_key VARCHAR(100), "
            "target_value FLOAT, baseline_value FLOAT, baseline_window_days INTEGER, evidence TEXT, owner VARCHAR(255), "
            "balancing_metrics JSON, status VARCHAR(20), provenance JSON, guardrails JSON, created_at DATETIME, updated_at DATETIME)"
        ))
        conn.execute(sa.text(
            "CREATE TABLE kpi_target_events (id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36), target_id VARCHAR(36), "
            "event VARCHAR(30), metric_key VARCHAR(100), at DATETIME, target_value FLOAT, baseline_value FLOAT)"
        ))


def test_icm_precreated_table_survives_downgrade_and_gets_missing_unique(tmp_path):
    migration = _load("icm_side_effect_dedupe.py", "_icm_guard_migration")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'icm_precreated.db'}")
    with engine.begin() as conn:
        conn.execute(sa.text(
            "CREATE TABLE icm_side_effects (id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36), "
            "idempotency_key VARCHAR(64), stage_id VARCHAR(100), run_id VARCHAR(100), created_at DATETIME)"
        ))
        conn.execute(sa.text(
            "INSERT INTO icm_side_effects (id, org_id, idempotency_key, stage_id, run_id, created_at) "
            "VALUES ('claim-1', 'org-1', 'key-1', 's1', 'r1', '2026-01-01')"
        ))
        with Operations.context(_context(conn)):
            migration.upgrade()

        uniques = {u["name"] for u in sa.inspect(conn).get_unique_constraints("icm_side_effects")}
        assert migration.UQ in uniques
        assert conn.execute(sa.text("SELECT count(*) FROM icm_side_effects")).scalar_one() == 1

        with Operations.context(_context(conn)):
            migration.downgrade()

    assert "icm_side_effects" in sa.inspect(engine).get_table_names()
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT id FROM icm_side_effects")).scalar_one() == "claim-1"
    engine.dispose()


def test_icm_table_created_by_migration_is_dropped(tmp_path):
    migration = _load("icm_side_effect_dedupe.py", "_icm_owned_migration")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'icm_owned.db'}")
    with engine.begin() as conn:
        with Operations.context(_context(conn)):
            migration.upgrade()
        conn.execute(sa.text(
            "INSERT INTO icm_side_effects (id, org_id, idempotency_key, stage_id, run_id, created_at) "
            "VALUES ('claim-2', 'org-1', 'key-2', 's1', 'r1', '2026-01-01')"
        ))
        with Operations.context(_context(conn)):
            migration.downgrade()

    assert "icm_side_effects" not in sa.inspect(engine).get_table_names()
    engine.dispose()


def test_schema_gaps_precreated_schema_survives_downgrade(tmp_path):
    migration = _load("schema_gaps_creds_crm_kpi.py", "_schema_gaps_guard_migration")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'schema_precreated.db'}")
    with engine.begin() as conn:
        _legacy_schema(conn, precreated=True)
        conn.execute(sa.text("INSERT INTO organizations (id, extra_data) VALUES ('org-1', '{}')"))
        conn.execute(sa.text(
            "INSERT INTO credentials (id, org_id, name, cred_type, data_enc, extra_data, status, version, scope) "
            "VALUES ('cred-1', 'org-1', 'key', 'bearer', 'enc', '{}', 'active', 3, '{}')"
        ))
        conn.execute(sa.text(
            "INSERT INTO credential_scopes (id, org_id, credential_id, scope_type, scope_id, created_at) "
            "VALUES ('scope-1', 'org-1', 'cred-1', 'agent', 'a1', '2026-01-01')"
        ))
        for account_id in ("acc-existing", "acc-extra"):
            conn.execute(sa.text(
                "INSERT INTO crm_accounts (id, org_id, name) VALUES (:id, 'org-1', 'A')"
            ), {"id": account_id})
        conn.execute(sa.text(
            "INSERT INTO crm_deals (id, org_id, lead_name, stage, extra_data, account_id, contact_id) "
            "VALUES ('deal-pre', 'org-1', 'L', 'mql', :extra, 'acc-existing', NULL)"
        ), {"extra": json.dumps({"account_id": "acc-extra"})})
        conn.execute(sa.text(
            "INSERT INTO kpi_targets (id, org_id, metric_key, target_value, baseline_value, baseline_window_days, "
            "evidence, owner, status, created_at, updated_at, balancing_metrics, provenance, guardrails) "
            "VALUES ('kt-pre', 'org-1', 'crm.win_rate', 0.7, 0.6, 30, 'query', 'sales', 'active', "
            "'2026-01-01', '2026-01-01', '[]', '{}', '{}')"
        ))
        with Operations.context(_context(conn)):
            migration.upgrade()

        inspector = sa.inspect(conn)
        assert "uq_kpi_target_org_metric" in {
            u["name"] for u in inspector.get_unique_constraints("kpi_targets")
        }
        assert "uq_credential_scope" in {
            u["name"] for u in inspector.get_unique_constraints("credential_scopes")
        }
        assert conn.execute(sa.text("SELECT version FROM credentials WHERE id='cred-1'")).scalar_one() == 3
        assert conn.execute(sa.text(
            "SELECT account_id FROM crm_deals WHERE id='deal-pre'"
        )).scalar_one() == "acc-existing"  # pre-existing pointer not overwritten

        with Operations.context(_context(conn)):
            migration.downgrade()

        tables = set(sa.inspect(conn).get_table_names())
        assert {"credential_events", "credential_scopes", "usage_attributions", "kpi_targets", "kpi_target_events"} <= tables
        cols = {c["name"] for c in sa.inspect(conn).get_columns("credentials")}
        assert {"status", "version", "scope"} <= cols
        assert conn.execute(sa.text("SELECT count(*) FROM credential_scopes")).scalar_one() == 1
        assert conn.execute(sa.text("SELECT count(*) FROM kpi_targets")).scalar_one() == 1
    engine.dispose()


def test_schema_gaps_backfill_preserves_pointers_and_skips_fake_metrics(tmp_path):
    migration = _load("schema_gaps_creds_crm_kpi.py", "_schema_gaps_backfill_migration")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'schema_legacy.db'}")
    with engine.begin() as conn:
        _legacy_schema(conn)
        kpi_extra = {
            "kpi_targets": {"targets": [
                {"id": "kt-ok", "metric_key": "crm.win_rate", "target_value": 0.7,
                 "baseline_value": 0.6, "baseline_window_days": 30},
                {"id": "kt-no-baseline", "metric_key": "crm.cycle_days", "target_value": 5},
                {"id": "kt-bad", "metric_key": "support.first_response", "target_value": "n/a",
                 "baseline_value": 10, "baseline_window_days": 7},
                {"id": "kt-no-window", "metric_key": "cost.per_call", "target_value": 1,
                 "baseline_value": 1},
            ]},
            "kpi_target_history": [],
        }
        conn.execute(sa.text("INSERT INTO organizations (id, extra_data) VALUES ('org-1', :extra)"), {
            "extra": json.dumps(kpi_extra),
        })
        for account_id in ("acc-existing", "acc-extra"):
            conn.execute(sa.text(
                "INSERT INTO crm_accounts (id, org_id, name) VALUES (:id, 'org-1', 'A')"
            ), {"id": account_id})
        for contact_id in ("con-existing", "con-extra"):
            conn.execute(sa.text(
                "INSERT INTO crm_contacts (id, org_id, name) VALUES (:id, 'org-1', 'C')"
            ), {"id": contact_id})
        conn.execute(sa.text(
            "INSERT INTO crm_deals (id, org_id, lead_name, stage, extra_data) "
            "VALUES ('deal-1', 'org-1', 'L', 'mql', :extra)"
        ), {"extra": json.dumps({"account_id": "acc-extra", "contact_id": "con-extra"})})
        conn.execute(sa.text(
            "INSERT INTO crm_deals (id, org_id, lead_name, stage, extra_data) VALUES "
            "('deal-2', 'org-1', 'L', 'mql', :extra)"
        ), {"extra": json.dumps({"account_id": "acc-extra", "contact_id": "con-extra"})})

        with Operations.context(_context(conn)):
            migration.upgrade()

        def links():
            return {
                row.id: (row.account_id, row.contact_id)
                for row in conn.execute(sa.text("SELECT id, account_id, contact_id FROM crm_deals"))
            }

        assert links() == {
            "deal-1": ("acc-extra", "con-extra"),
            "deal-2": ("acc-extra", "con-extra"),
        }
        targets = {
            row.id: (row.target_value, row.baseline_value, row.baseline_window_days)
            for row in conn.execute(sa.text(
                "SELECT id, target_value, baseline_value, baseline_window_days FROM kpi_targets"
            ))
        }
        assert targets == {"kt-ok": (0.7, 0.6, 30)}

        # Authoritative pointer set after first upgrade must survive a repeat.
        conn.execute(sa.text(
            "UPDATE crm_deals SET account_id='acc-existing', contact_id='con-existing' WHERE id='deal-1'"
        ))
        with Operations.context(_context(conn)):
            migration.upgrade()
        assert links() == {
            "deal-1": ("acc-existing", "con-existing"),
            "deal-2": ("acc-extra", "con-extra"),
        }
        assert conn.execute(sa.text("SELECT count(*) FROM kpi_targets")).scalar_one() == 1

        with Operations.context(_context(conn)):
            migration.downgrade()

        assert "kpi_targets" not in sa.inspect(conn).get_table_names()
        assert {c["name"] for c in sa.inspect(conn).get_columns("crm_deals")} >= {"id", "extra_data"}
        assert conn.execute(sa.text("SELECT count(*) FROM crm_deals")).scalar_one() == 2
    engine.dispose()


def test_schema_gaps_backfill_skips_boolean_metrics(tmp_path):
    migration = _load("schema_gaps_creds_crm_kpi.py", "_schema_gaps_bool_migration")
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'schema_bool.db'}")
    with engine.begin() as conn:
        _legacy_schema(conn)
        kpi_extra = {
            "kpi_targets": {"targets": [
                {"id": "kt-valid", "metric_key": "crm.win_rate", "target_value": 0.7,
                 "baseline_value": 0.6, "baseline_window_days": 30},
                {"id": "kt-numeric-strings", "metric_key": "crm.cycle_days", "target_value": "5",
                 "baseline_value": "4.5", "baseline_window_days": "14"},
                {"id": "kt-bool-target", "metric_key": "bool.target", "target_value": True,
                 "baseline_value": 0.6, "baseline_window_days": 30},
                {"id": "kt-bool-baseline", "metric_key": "bool.baseline", "target_value": 0.7,
                 "baseline_value": True, "baseline_window_days": 30},
                {"id": "kt-bool-window", "metric_key": "bool.window", "target_value": 0.7,
                 "baseline_value": 0.6, "baseline_window_days": True},
                {"id": "kt-bool-strings", "metric_key": "bool.strings", "target_value": "TRUE",
                 "baseline_value": "false", "baseline_window_days": "true"},
                {"id": "kt-inf-window", "metric_key": "inf.window", "target_value": 0.7,
                 "baseline_value": 0.6, "baseline_window_days": float("inf")},
            ]},
            "kpi_target_history": [],
        }
        conn.execute(sa.text("INSERT INTO organizations (id, extra_data) VALUES ('org-1', :extra)"), {
            "extra": json.dumps(kpi_extra),
        })
        with Operations.context(_context(conn)):
            migration.upgrade()

        targets = {
            row.id: (row.target_value, row.baseline_value, row.baseline_window_days)
            for row in conn.execute(sa.text(
                "SELECT id, target_value, baseline_value, baseline_window_days FROM kpi_targets"
            ))
        }
        assert targets == {
            "kt-valid": (0.7, 0.6, 30),
            "kt-numeric-strings": (5.0, 4.5, 14),
        }
        assert "kt-inf-window" not in targets
    engine.dispose()
