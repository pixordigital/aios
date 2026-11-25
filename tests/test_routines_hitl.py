from types import SimpleNamespace

import pytest

from aios.core.routine_enforcement import (
    ROUTINE_SIDE_EFFECT_APPROVAL_TOOL,
    RoutineSideEffectBlocked,
    enforce_routine_side_effect,
    request_routine_side_effect_approval,
)


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt):
        try:
            compiled = stmt.compile(compile_kwargs={"literal_binds": True})
            s = str(compiled)
        except Exception:
            s = str(stmt)
        import re
        m = re.search(r"pending_actions\.id\s*=\s*'([^']+)'", s)
        if m:
            want = m.group(1)
            return _Result([r for r in self.rows if str(getattr(r, "id", "")) == want])
        return _Result(self.rows)

    def add(self, row):
        self.added.append(row)
        self.rows.append(row)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class _AgentDB:
    def __init__(self, agent):
        self.agent = agent
        self.rows = []
        self.added = []
        self.commits = 0

    async def get(self, _model, _id):
        return self.agent

    async def execute(self, _stmt):
        return _Result(self.rows)

    def add(self, row):
        self.added.append(row)
        self.rows.append(row)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        return None


def _routine(**kw):
    base = dict(routine_id="r1", org_id="o1", source_type="event_subscription", mode="proactive")
    base.update(kw)
    return SimpleNamespace(**base)


def _approval_row(*, approved=True, org_id="o1", routine_id="r1", action="send", key="k1", fp="fp1"):
    return SimpleNamespace(
        status="approved" if approved else "rejected",
        decided_by="user1" if approved else None,
        org_id=org_id,
        tool_args={
            "_routine_approved_action": {
                "org_id": org_id,
                "routine_id": routine_id,
                "action": action,
                "idempotency_key": key,
                "approved_fingerprint": fp,
            }
        },
    )


@pytest.mark.asyncio
async def test_proactive_side_effect_denied_without_approval():
    with pytest.raises(RoutineSideEffectBlocked, match="explicit approval required"):
        await enforce_routine_side_effect(
            db=_FakeDB([]),
            routine=_routine(mode="proactive"),
            action="dispatch",
            side_effects=["external_send"],
            approval_required=True,
            idempotency_key="idem-1",
            approved=False,
        )


@pytest.mark.asyncio
async def test_approved_path_allowed_with_db_evidence():
    row = _approval_row(routine_id="r1", action="dispatch", key="idem-2", fp="fp-1")
    await enforce_routine_side_effect(
        db=_FakeDB([row]),
        routine=_routine(routine_id="r1"),
        action="dispatch",
        side_effects=["external_send"],
        approval_required=True,
        idempotency_key="idem-2",
        approved=True,
        approval_fingerprint="fp-1",
    )


@pytest.mark.asyncio
async def test_missing_idempotency_or_org_denied():
    with pytest.raises(RoutineSideEffectBlocked, match="missing routine_id/action/idempotency_key"):
        await enforce_routine_side_effect(
            db=_FakeDB([]),
            routine=_routine(routine_id="r1", org_id="o1"),
            action="dispatch",
            side_effects=["external_send"],
            approval_required=True,
            idempotency_key="",
            approved=True,
        )

    with pytest.raises(RoutineSideEffectBlocked, match="missing org_id"):
        await enforce_routine_side_effect(
            db=_FakeDB([]),
            routine=_routine(routine_id="r1", org_id=None),
            action="dispatch",
            side_effects=["external_send"],
            approval_required=True,
            idempotency_key="idem-3",
            approved=True,
        )


@pytest.mark.asyncio
async def test_reject_timeout_missing_evidence_no_dispatch(monkeypatch):
    from aios.tasks import jobs

    agent = SimpleNamespace(
        id="a1",
        org_id="o1",
        name="A",
        status="active",
        governance_config={"autonomous": False},
        extra_data={"event_subscriptions": ["message.received"]},
    )

    async def _fail(*_a, **_k):
        raise AssertionError("agent should not run")

    monkeypatch.setattr("aios.core.agent.AgentRuntime.run", _fail)
    monkeypatch.setattr("aios.core.autonomous_agent.AutonomousAgent.run", _fail)

    payload = {
        "agent_id": "a1",
        "org_id": "o1",
        "event": {
            "event_id": "e1",
            "event_type": "message.received",
            "org_id": "o1",
            "ts": "2026-01-01T00:00:00Z",
            "payload": {},
            "idempotency_key": "evt-1",
        },
        "routine": {"routine_id": "event_subscription:a1:s1", "approved": False, "side_effects": ["external_send"]},
    }

    db = _AgentDB(agent)
    monkeypatch.setattr("aios.db.engine.async_session", lambda: _Ctx(db))
    res = await jobs.proactive_event_job({}, payload)
    assert res["blocked"] is True
    assert "explicit approval required" in res["reason"]
    assert res["approval_requested"] is True
    assert res["approval"]["status"] == "pending"
    assert len(db.added) == 1
    row = db.added[0]
    assert row.tool_name == ROUTINE_SIDE_EFFECT_APPROVAL_TOOL
    marker = row.tool_args["_routine_approved_action"]
    assert marker["org_id"] == "o1"
    assert marker["routine_id"] == "event_subscription:a1:s1"
    assert marker["action"] == "proactive_event_dispatch"
    assert marker["idempotency_key"] == res["idempotency_key"]
    assert len(db.added) == 1
    row = db.added[0]
    assert row.tool_name == ROUTINE_SIDE_EFFECT_APPROVAL_TOOL
    marker = row.tool_args["_routine_approved_action"]
    assert marker["org_id"] == "o1"
    assert marker["routine_id"] == "event_subscription:a1:s1"
    assert marker["action"] == "proactive_event_dispatch"
    assert marker["idempotency_key"]


@pytest.mark.asyncio
async def test_duplicate_idempotency_guard_blocks_replay():
    # Same evidence but different idempotency key must be denied (no replay/fabrication).
    row = _approval_row(routine_id="r1", action="dispatch", key="idem-a", fp="fp-1")
    with pytest.raises(RoutineSideEffectBlocked, match="DB approval evidence required"):
        await enforce_routine_side_effect(
            db=_FakeDB([row]),
            routine=_routine(routine_id="r1"),
            action="dispatch",
            side_effects=["external_send"],
            approval_required=True,
            idempotency_key="idem-b",
            approved=True,
            approval_fingerprint="fp-1",
        )


@pytest.mark.asyncio
async def test_request_routine_approval_idempotent_no_duplicate_rows():
    db = _FakeDB([])
    kw = dict(
        org_id="o1",
        routine_id="r1",
        action="dispatch",
        idempotency_key="idem-1",
        side_effects=["external_send"],
        mode="proactive",
        source_type="event_subscription",
        context_summary="ctx",
        approval_fingerprint="fp1",
    )
    first = await request_routine_side_effect_approval(db, **kw)
    second = await request_routine_side_effect_approval(db, **kw)
    assert first["status"] == "pending"
    assert second["existing"] is True
    assert second["approval_id"] == first["approval_id"]
    assert len(db.added) == 1


@pytest.mark.asyncio
async def test_approved_marker_allows_after_explicit_decision(monkeypatch):
    from aios.api import approvals as approvals_api
    from aios.core.approval import ApprovalManager

    mgr = ApprovalManager(timeout=1)
    monkeypatch.setattr(approvals_api, "approval_manager", mgr)

    db = _FakeDB([])
    req = await request_routine_side_effect_approval(
        db,
        org_id="o1",
        routine_id="r1",
        action="dispatch",
        idempotency_key="idem-2",
        side_effects=["external_send"],
        mode="proactive",
        source_type="event_subscription",
        context_summary="ctx",
        approval_fingerprint="fp-2",
    )
    row = db.added[0]
    row.status = "approved"
    row.decided_by = "u1"

    async def _fake_write(*_a, **_k):
        return True

    monkeypatch.setattr(ApprovalManager, "_write_db_status", staticmethod(_fake_write))
    ok = await mgr.approve(req["approval_id"], decided_by="u1", org_id="o1")
    assert ok is True

    await enforce_routine_side_effect(
        db=db,
        routine=_routine(routine_id="r1", org_id="o1"),
        action="dispatch",
        side_effects=["external_send"],
        approval_required=True,
        idempotency_key="idem-2",
        approved=True,
        approval_fingerprint="fp-2",
    )


@pytest.mark.asyncio
async def test_cross_org_marker_not_accepted():
    row = _approval_row(org_id="o2", routine_id="r1", action="dispatch", key="idem-3", fp="fp3")
    with pytest.raises(RoutineSideEffectBlocked, match="DB approval evidence required"):
        await enforce_routine_side_effect(
            db=_FakeDB([row]),
            routine=_routine(routine_id="r1", org_id="o1"),
            action="dispatch",
            side_effects=["external_send"],
            approval_required=True,
            idempotency_key="idem-3",
            approved=True,
            approval_fingerprint="fp3",
        )


class _Ctx:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_approval_dispatch_enqueues_whitelisted_job(monkeypatch):
    from aios.api import approvals as approvals_api
    from aios.core.approval import ApprovalManager
    from aios.db.models import PendingAction as DBAction
    from aios.db.models import User

    mgr = ApprovalManager(timeout=1)
    monkeypatch.setattr(approvals_api, "approval_manager", mgr)

    db = _FakeDB([])
    req = await request_routine_side_effect_approval(
        db,
        org_id="o1",
        routine_id="r1",
        action="proactive_event_dispatch",
        idempotency_key="idem-d1",
        side_effects=["external_send"],
        mode="proactive",
        source_type="event_subscription",
        context_summary="ctx",
        dispatch_job="proactive_event_job",
        dispatch_payload={"agent_id": "a1", "org_id": "o1", "event": {"event_type": "x"}},
    )
    row = db.added[0]
    row.id = req["approval_id"]
    row.org_id = "o1"
    row.status = "pending"
    row.decided_by = None

    async def _fake_write(action_id, status, decided_by, org_id):
        row.status = status
        row.decided_by = decided_by
        row.org_id = org_id
        return True

    monkeypatch.setattr(ApprovalManager, "_write_db_status", staticmethod(_fake_write))

    enqueued = []

    async def _fake_enqueue(name, payload):
        enqueued.append((name, payload))

    monkeypatch.setattr("aios.tasks.queue.enqueue_job", _fake_enqueue)
    async def _ok(*a, **k):
        return None
    monkeypatch.setattr(approvals_api, "verify_org_access_async", _ok)
    async def _allow(*a, **k):
        return None

    monkeypatch.setattr(approvals_api, "_require_decision_authority", _allow)
    monkeypatch.setattr(approvals_api, "_is_self_approval", lambda *a, **k: False)

    user = SimpleNamespace(id="u1", org_id="o1", role="admin")
    res = await approvals_api.approve_action(req["approval_id"], db=db, user=user)
    assert res["status"] == "approved"
    assert res["dispatch"]["dispatched"] is True
    assert enqueued[0][0] == "aios.tasks.jobs.proactive_event_job"
    assert enqueued[0][1]["routine"]["approved"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_job", ["evil_job", "evil.workday_job"])
async def test_approval_dispatch_rejects_unknown_job(monkeypatch, bad_job):
    from aios.api import approvals as approvals_api
    from aios.core.approval import ApprovalManager

    mgr = ApprovalManager(timeout=1)
    monkeypatch.setattr(approvals_api, "approval_manager", mgr)
    db = _FakeDB([])
    # create row directly with bad dispatch marker
    row = SimpleNamespace(
        id="ap1", org_id="o1", tool_name=ROUTINE_SIDE_EFFECT_APPROVAL_TOOL, status="pending", decided_by=None,
        tool_args={"_routine_approved_action": {"org_id": "o1", "routine_id": "r1", "action": "a", "idempotency_key": "k", "dispatch_job": bad_job, "dispatch_payload": {}}}
    )
    db.add(row)

    async def _fake_write(action_id, status, decided_by, org_id):
        row.status = status
        row.decided_by = decided_by
        return True

    monkeypatch.setattr(ApprovalManager, "_write_db_status", staticmethod(_fake_write))
    called = []

    async def _fake_enqueue(*a, **k):
        called.append((a, k))

    monkeypatch.setattr("aios.tasks.queue.enqueue_job", _fake_enqueue)
    async def _ok(*a, **k):
        return None
    monkeypatch.setattr(approvals_api, "verify_org_access_async", _ok)
    async def _allow(*a, **k):
        return None
    monkeypatch.setattr(approvals_api, "_require_decision_authority", _allow)
    monkeypatch.setattr(approvals_api, "_is_self_approval", lambda *a, **k: False)

    user = SimpleNamespace(id="u1", org_id="o1", role="admin")
    res = await approvals_api.approve_action("ap1", db=db, user=user)
    assert res["status"] == "approved"
    assert res["dispatch"]["dispatched"] is False
    assert res["dispatch"]["reason"] == "job_not_whitelisted"
    assert called == []


@pytest.mark.asyncio
async def test_reject_does_not_dispatch(monkeypatch):
    from aios.api import approvals as approvals_api
    from aios.core.approval import ApprovalManager

    mgr = ApprovalManager(timeout=1)
    monkeypatch.setattr(approvals_api, "approval_manager", mgr)
    db = _FakeDB([])
    row = SimpleNamespace(
        id="ap2", org_id="o1", tool_name=ROUTINE_SIDE_EFFECT_APPROVAL_TOOL, status="pending", decided_by=None,
        tool_args={"_routine_approved_action": {"org_id": "o1", "routine_id": "r1", "action": "a", "idempotency_key": "k", "dispatch_job": "proactive_event_job", "dispatch_payload": {}}}
    )
    db.add(row)

    async def _fake_write(action_id, status, decided_by, org_id):
        row.status = status
        row.decided_by = decided_by
        return True

    monkeypatch.setattr(ApprovalManager, "_write_db_status", staticmethod(_fake_write))
    called = []
    async def _fake_enqueue(*a, **k):
        called.append((a, k))
    monkeypatch.setattr("aios.tasks.queue.enqueue_job", _fake_enqueue)
    async def _ok(*a, **k):
        return None
    monkeypatch.setattr(approvals_api, "verify_org_access_async", _ok)
    async def _allow(*a, **k):
        return None
    monkeypatch.setattr(approvals_api, "_require_decision_authority", _allow)
    monkeypatch.setattr(approvals_api, "_is_self_approval", lambda *a, **k: False)

    user = SimpleNamespace(id="u1", org_id="o1", role="admin")
    res = await approvals_api.reject_action("ap2", db=db, user=user)
    assert res["status"] == "rejected"
    assert called == []
