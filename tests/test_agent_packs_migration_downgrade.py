"""Agent-pack downgrade must not delete approval rows to restore NOT NULL."""

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


def _prepare_upgraded(conn):
    migration = _load_migration()
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
    return migration


def _downgrade(conn, migration):
    with Operations.context(MigrationContext.configure(conn)):
        migration.downgrade()
    conn.commit()


def test_downgrade_preserves_null_linked_approval_and_skips_column_restore():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        migration = _prepare_upgraded(conn)
        conn.execute(sa.text("INSERT INTO pending_actions (id) VALUES ('p1')"))
        conn.commit()

        _downgrade(conn, migration)

        row = conn.execute(sa.text(
            "SELECT id, agent_id, conversation_id FROM pending_actions WHERE id = 'p1'"
        )).one()
        assert tuple(row) == ("p1", None, None)
        assert _pending_columns(conn)["agent_id"]["nullable"] is True
        assert _pending_columns(conn)["conversation_id"]["nullable"] is True
        assert "agent_packs" not in sa.inspect(conn).get_table_names()


def test_downgrade_restores_not_null_when_no_null_links_exist():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        migration = _prepare_upgraded(conn)
        conn.execute(sa.text("INSERT INTO agents (id) VALUES ('a1')"))
        conn.execute(sa.text("INSERT INTO conversations (id) VALUES ('c1')"))
        conn.execute(sa.text(
            "INSERT INTO pending_actions (id, agent_id, conversation_id) VALUES ('p2', 'a1', 'c1')"
        ))
        conn.commit()

        _downgrade(conn, migration)

        row = conn.execute(sa.text(
            "SELECT id, agent_id, conversation_id FROM pending_actions WHERE id = 'p2'"
        )).one()
        assert tuple(row) == ("p2", "a1", "c1")
        assert _pending_columns(conn)["agent_id"]["nullable"] is False
        assert _pending_columns(conn)["conversation_id"]["nullable"] is False
        assert "agent_packs" not in sa.inspect(conn).get_table_names()
