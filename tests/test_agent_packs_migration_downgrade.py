"""Agent-pack migration downgrade must restore the pre-upgrade NOT NULL contract."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "b2c3d4e5f6a7_agent_packs.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("agent_packs_migration_under_test", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pending_columns(conn):
    return {c["name"]: c for c in sa.inspect(conn).get_columns("pending_actions")}


def test_agent_packs_downgrade_removes_null_links_before_restoring_not_null():
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(sa.text("CREATE TABLE organizations (id VARCHAR(36) PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE agents (id VARCHAR(36) PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE conversations (id VARCHAR(36) PRIMARY KEY)"))
        conn.execute(sa.text(
            "CREATE TABLE pending_actions ("
            "id VARCHAR(36) PRIMARY KEY, "
            "agent_id VARCHAR(36) CONSTRAINT fk_pa_agent REFERENCES agents(id), "
            "conversation_id VARCHAR(36) CONSTRAINT fk_pa_conv REFERENCES conversations(id))"
        ))
        conn.commit()

        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        conn.commit()
        assert _pending_columns(conn)["agent_id"]["nullable"] is True
        assert _pending_columns(conn)["conversation_id"]["nullable"] is True

        conn.execute(sa.text("INSERT INTO pending_actions (id) VALUES ('p1')"))
        conn.commit()

        with Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()
        conn.commit()

        assert _pending_columns(conn)["agent_id"]["nullable"] is False
        assert _pending_columns(conn)["conversation_id"]["nullable"] is False
        assert conn.execute(sa.text("SELECT COUNT(*) FROM pending_actions")).scalar_one() == 0
        assert "agent_packs" not in sa.inspect(conn).get_table_names()
