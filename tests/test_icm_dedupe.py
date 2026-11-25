"""ICM durable side-effect dedupe — temp SQLite, no live DB or provider."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from aios.db.engine import Base
from aios.db.models import Organization, PendingAction
from aios.icm.adapter import ICMStageAdapter, SideEffectDuplicateError
from aios.icm.contracts import StageManifest, manifest_fingerprint
from aios.icm.dedupe_model import ICMSideEffect

REPO = Path(__file__).resolve().parents[1]
MIGRATION = REPO / "alembic" / "versions" / "icm_side_effect_dedupe.py"


def _adapter(session=None, *, org_id="org-1", run_id="run-1"):
    manifest = StageManifest.model_validate({
        "id": "notify_stage",
        "version": "1.0.0",
        "mode": "deterministic",
        "side_effects": True,
    })
    node = SimpleNamespace(
        id="n1", tool_name="send_email", stage_id="notify_stage", stage_manifest=manifest
    )
    return ICMStageAdapter(
        node=node,
        storage_root="data",
        org_id=org_id,
        run_id=run_id,
        preapproved={
            "approved": True,
            "approval_id": "appr-1" if org_id == "org-1" else "appr-2",
            "approved_fingerprint": manifest_fingerprint(manifest),
            "actions": ["send_email"],
        },
        db_session=session,
    )


@pytest.fixture
def db(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'dedupe.db'}")
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__,
            PendingAction.__table__,
            ICMSideEffect.__table__,
        ],
    )
    with Session(engine) as session:
        session.add(Organization(id="org-1", name="Org 1", slug="org-1"))
        session.add(Organization(id="org-2", name="Org 2", slug="org-2"))
        for idx, org in enumerate(("org-1", "org-2"), 1):
            session.add(
                PendingAction(
                    id=f"appr-{idx}",
                    org_id=org,
                    agent_id="a1",
                    conversation_id="c1",
                    tool_name="send_email",
                    status="approved",
                    decided_by="user-1",
                )
            )
        session.commit()
        yield session
    engine.dispose()


def _rows(session):
    return session.execute(sa.select(ICMSideEffect)).scalars().all()


def test_first_claim_persists_durable_row(db):
    key = _adapter(db).enforce_execution({"task_id": "task-1"}, action="send_email")

    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0].org_id == "org-1"
    assert rows[0].idempotency_key == key
    assert rows[0].stage_id == "notify_stage"
    assert rows[0].run_id == "run-1"
    assert rows[0].created_at is not None


def test_same_run_retry_is_idempotent(db):
    first_key = _adapter(db).enforce_execution({"task_id": "task-1"}, action="send_email")

    retry = _adapter(db, run_id="run-1")
    shared = {"task_id": "task-1"}
    retry_key = retry.enforce_execution(shared, action="send_email")

    assert retry_key == first_key
    assert retry.side_effect_recorded
    assert shared["_icm_side_effect_keys"] == {first_key}
    assert len(_rows(db)) == 1


def test_cross_run_duplicate_fails_closed(db):
    _adapter(db).enforce_execution({"task_id": "task-1"}, action="send_email")

    other = _adapter(db, run_id="run-2")
    shared = {"task_id": "task-1"}
    with pytest.raises(SideEffectDuplicateError, match="already claimed"):
        other.enforce_execution(shared, action="send_email")

    assert not other.side_effect_recorded
    assert "_icm_side_effect_keys" not in shared
    assert len(_rows(db)) == 1


def test_same_key_other_org_is_independent(db):
    first_key = _adapter(db, org_id="org-1").enforce_execution(
        {"task_id": "task-1"}, action="send_email"
    )
    second_key = _adapter(db, org_id="org-2").enforce_execution(
        {"task_id": "task-1"}, action="send_email"
    )

    assert first_key == second_key
    assert {row.org_id for row in _rows(db)} == {"org-1", "org-2"}


def test_shared_dict_session_is_supported(db):
    adapter = _adapter()
    shared = {"task_id": "task-1", "icm_db_session": db}

    adapter.enforce_execution(shared, action="send_email")

    assert len(_rows(db)) == 1


def test_in_memory_dedupe_unchanged_without_session():
    adapter = _adapter()
    shared = {"task_id": "task-1"}

    first = adapter.enforce_execution(shared, action="send_email")
    second = adapter.enforce_execution(shared, action="send_email")

    assert second == first
    assert adapter.side_effect_recorded
    assert shared["_icm_side_effect_keys"] == {first}


def test_unique_race_resolves_by_run_id():
    class RacingSession:
        def __init__(self, winner_run):
            self.winner_run = winner_run
            self.rolled_back = False

        def execute(self, *args, **kwargs):
            if "pending_actions" in str(args[0] if args else ""):
                return SimpleNamespace(
                    scalar_one_or_none=lambda: SimpleNamespace(decided_by="user-1")
                )
            row = None
            if self.rolled_back:
                row = SimpleNamespace(run_id=self.winner_run)
            return SimpleNamespace(scalar_one_or_none=lambda: row)

        def add(self, row):
            pass

        def commit(self):
            raise IntegrityError("INSERT", {}, Exception("unique violation"))

        def rollback(self):
            self.rolled_back = True

    retry_session = RacingSession("run-1")
    shared = {"task_id": "task-1"}
    key = _adapter(retry_session).enforce_execution(shared, action="send_email")
    assert retry_session.rolled_back
    assert shared["_icm_side_effect_keys"] == {key}

    with pytest.raises(SideEffectDuplicateError):
        _adapter(RacingSession("run-2")).enforce_execution(
            {"task_id": "task-1"}, action="send_email"
        )


def test_store_error_fails_closed():
    class BrokenSession:
        def execute(self, *args, **kwargs):
            if "pending_actions" in str(args[0] if args else ""):
                return SimpleNamespace(
                    scalar_one_or_none=lambda: SimpleNamespace(decided_by="user-1")
                )
            raise SQLAlchemyError("down")

        def rollback(self):
            pass

    adapter = _adapter(BrokenSession())
    shared = {"task_id": "task-1"}

    with pytest.raises(RuntimeError, match="unavailable"):
        adapter.enforce_execution(shared, action="send_email")

    assert not adapter.side_effect_recorded
    assert "_icm_side_effect_keys" not in shared


def test_migration_upgrade_downgrade_on_sqlite(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    spec = importlib.util.spec_from_file_location("icm_dedupe_migration", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()

    insp = sa.inspect(engine)
    assert "icm_side_effects" in insp.get_table_names()
    columns = {c["name"] for c in insp.get_columns("icm_side_effects")}
    assert {"org_id", "idempotency_key", "stage_id", "run_id", "created_at"} <= columns
    uniques = {u["name"] for u in insp.get_unique_constraints("icm_side_effects")}
    assert "uq_icm_side_effects_org_key" in uniques

    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()

    assert "icm_side_effects" not in sa.inspect(engine).get_table_names()
    engine.dispose()
