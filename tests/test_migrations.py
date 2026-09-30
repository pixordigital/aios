"""Migration hygiene tests.

Regression: two migrations created tables/columns unconditionally while
init_db() also runs SQLAlchemy create_all. `alembic upgrade head` therefore
failed on every container boot and alembic_version stayed pinned, so every
later migration was silently blocked (the entrypoint swallowed the error).
"""

import ast
from pathlib import Path

VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"

# Migrations that create tables must tolerate them already existing.
_MUST_GUARD = {
    "s4l3sg0a1s01_sales_goals.py",
    "h4b5c6d7e8f9_blacklist_tamper.py",
}


def _src(name):
    return (VERSIONS / name).read_text()


def test_versions_dir_exists():
    assert VERSIONS.is_dir()


def test_no_duplicate_revision_ids():
    import re

    revs = {}
    for p in VERSIONS.glob("*.py"):
        m = re.search(r'^revision = ["\'](.+?)["\']', p.read_text(), re.M)
        if m:
            revs.setdefault(m.group(1), []).append(p.name)
    dupes = {r: f for r, f in revs.items() if len(f) > 1}
    assert not dupes, f"duplicate revision ids: {dupes}"


def test_create_table_migrations_are_guarded():
    for name in _MUST_GUARD:
        src = _src(name)
        assert "has_table" in src, f"{name}: create_table without a has_table guard"
        assert 'sa.inspect' in src, f"{name}: needs sa.inspect to check the schema"


def test_blacklist_migration_guards_added_columns():
    src = _src("h4b5c6d7e8f9_blacklist_tamper.py")
    assert "get_columns" in src, "must check existing organizations columns before adding"
    assert "missing" in src or "present" in src


def test_usage_records_unique_migration_exists():
    p = VERSIONS / "u1q2r3s4t5u6_usage_records_unique.py"
    assert p.exists()
    src = p.read_text()
    assert "create_unique_constraint" in src
    assert "ROW_NUMBER" in src, "must dedupe existing rows before adding the constraint"


def test_model_declares_the_constraint():
    from sqlalchemy import UniqueConstraint

    from aios.db.models import UsageRecord

    names = {c.name for c in UsageRecord.__table__.constraints if isinstance(c, UniqueConstraint)}
    assert "uq_usage_records_org_date" in names


def test_every_migration_parses():
    for p in VERSIONS.glob("*.py"):
        ast.parse(p.read_text())  # raises on syntax error


def test_messages_dedup_migration_exists():
    p = VERSIONS / "x4y5z6a7b8c9_messages_dedup.py"
    assert p.exists()
    src = p.read_text()
    assert "uq_messages_org_provider_msg" in src
    assert "create_unique_constraint" in src


def test_message_model_declares_dedup_constraint():
    from sqlalchemy import UniqueConstraint

    from aios.db.models import Message

    names = {c.name for c in Message.__table__.constraints if isinstance(c, UniqueConstraint)}
    assert "uq_messages_org_provider_msg" in names


def test_inbound_populates_provider_message_id():
    """Redeliveries duplicated Message rows because channel_message_id stayed NULL.

    The worker must derive it from provider data (Evolution msg_id, Slack ts).
    """
    from pathlib import Path

    src = Path("aios/tasks/jobs.py").read_text()
    assert 'extra.get("msg_id")' in src
    assert "channel_message_id=provider_msg_id" in src
    assert "duplicate" in src
