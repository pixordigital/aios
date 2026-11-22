"""OCP foundations: deterministic authority, task lifecycle and decisions."""

from datetime import datetime, timedelta

import pytest

from aios.db.models import Base
from aios.governance.ocp import (
    AuthorityGrant,
    DecisionRecord,
    Department,
    SharedTask,
    TransitionError,
    authorize,
    can_approve,
    can_transition,
    decide,
    decision_level,
    missing_decision_fields,
    task_budget_check,
    transition_task,
)


def test_tables_registered():
    for name in (
        "departments",
        "department_members",
        "authority_grants",
        "shared_tasks",
        "org_goals",
        "decision_records",
        "org_events",
    ):
        assert name in Base.metadata.tables


def test_task_lifecycle_is_closed():
    assert can_transition("new", "triage")
    assert can_transition("review", "completed")
    assert not can_transition("new", "completed")  # cannot skip the ladder
    assert not can_transition("completed", "in_progress")  # terminal


def test_transition_records_history():
    task = SharedTask(org_id="o", title="t", status="ready")
    transition_task(task, "in_progress", "agent", "a1")
    assert task.status == "in_progress"
    assert task.audit_history[-1]["from"] == "ready"
    with pytest.raises(TransitionError):
        transition_task(task, "triage", "agent", "a1")


def test_authorize_respects_validity_scope_and_revocation():
    now = datetime(2026, 11, 22, 12, 0)
    grant = AuthorityGrant(
        org_id="o",
        subject_type="agent",
        subject_id="a1",
        role="manager",
        actions=["task:*"],
        resources={"task": ["t1"]},
        valid_until=now + timedelta(days=1),
    )
    assert authorize([grant], "task:transition", resource_type="task", resource_id="t1", now=now)[0]
    assert not authorize([grant], "task:transition", resource_type="task", resource_id="t2", now=now)[0]
    assert not authorize([grant], "budget:write", now=now)[0]

    grant.revoked_at = now
    assert not authorize([grant], "task:transition", resource_type="task", resource_id="t1", now=now)[0]

    grant.revoked_at = None
    assert not authorize([grant], "task:transition", now=now + timedelta(days=2))[0]


def test_ocp_strict_default_deny_flag():
    from aios.governance.ocp import ocp_strict_default_deny

    assert ocp_strict_default_deny(None) is False
    assert ocp_strict_default_deny({}) is False
    assert ocp_strict_default_deny({"ocp": {"strict_default_deny": True}}) is True
    assert ocp_strict_default_deny({"ocp": {"strict_default_deny": False}}) is False


def test_link_external_approval_bridge():
    from aios.governance.ocp import link_external_approval

    record = DecisionRecord(org_id="o", title="t", justification={"proposal": "p"})
    link_external_approval(record, ref_type="pending_action", ref_id="pa1", status="approved", note="ok")
    refs = record.justification["_external_approvals"]
    assert len(refs) == 1
    assert refs[0]["ref_type"] == "pending_action"
    assert refs[0]["ref_id"] == "pa1"
    assert refs[0]["status"] == "approved"
    with pytest.raises(ValueError, match="ref_type and ref_id"):
        link_external_approval(record, ref_type="", ref_id="x")


def test_decision_levels_and_founder_gate():
    assert decision_level("execute_approved_process") == 1
    assert decision_level("new_integration") == 2
    assert decision_level("sensitive_data_processing") == 3
    assert decision_level("unclassified_change") == 2  # fail closed to material
    assert can_approve(1, is_founder=False)
    assert not can_approve(2, is_founder=False)
    assert can_approve(2, is_founder=True)


def test_decide_requires_full_protocol():
    record = DecisionRecord(org_id="o", title="t", justification={"proposal": "p"})
    with pytest.raises(ValueError, match="missing"):
        decide(record, approve=True, founder_id="u1")
    assert "risks" in missing_decision_fields({"proposal": "p"})

    from aios.governance.ocp import DECISION_PROTOCOL_FIELDS

    record.justification = {f: "x" for f in DECISION_PROTOCOL_FIELDS}
    decide(record, approve=False, founder_id="u1")
    assert record.status == "rejected"
    assert record.decided_by == "u1"


def test_execute_decision_moves_linked_ready_tasks():
    from aios.governance.ocp import DecisionRecord, SharedTask, execute_decision

    task = SharedTask(org_id="o", title="t", status="ready")
    record = DecisionRecord(
        org_id="o", title="t", status="approved", linked_task_ids=[task.id],
    )
    executed = execute_decision(record, [task], actor_type="agent", actor_id="a1")
    assert executed.status == "executed"
    assert task.status == "in_progress"
    assert task.audit_history[-1]["to"] == "in_progress"


def test_execute_decision_requires_approved_decision():
    from aios.governance.ocp import DecisionRecord, SharedTask, execute_decision

    task = SharedTask(org_id="o", title="t", status="ready")
    record = DecisionRecord(org_id="o", title="t", status="proposed", linked_task_ids=[task.id])
    with pytest.raises(ValueError, match="approved"):
        execute_decision(record, [task])


def test_execute_decision_requires_linked_tasks():
    from aios.governance.ocp import DecisionRecord, SharedTask, execute_decision

    task = SharedTask(org_id="o", title="t", status="ready")
    record = DecisionRecord(org_id="o", title="t", status="approved")
    with pytest.raises(ValueError, match="linked tasks"):
        execute_decision(record, [task])


def test_task_budget_check():
    task = SharedTask(org_id="o", title="t", status="ready", budget_id="b1")
    assert task_budget_check(task, []) == ("deny", "task budget not found")
    task2 = SharedTask(org_id="o", title="t", status="ready", budget_id=None)
    assert task_budget_check(task2, []) == ("unknown", "task has no budget")
    task3 = SharedTask(org_id="o", title="t", status="ready", budget_id="b1")

    class _B:
        id = "b1"
        amount_brl = 100.0

    assert task_budget_check(task3, [_B()]) == ("allow", "task budget within limit")
    assert task_budget_check(task3, [_B()], spent_brl=101.0) == ("deny", "task budget exceeded")


async def test_department_and_task_roundtrip(test_session):
    from aios.db.models import Organization

    org = Organization(name="OCP Org", slug="ocp-org")
    test_session.add(org)
    await test_session.flush()

    dept = Department(org_id=org.id, name="Sales", slug="sales")
    test_session.add(dept)
    await test_session.flush()

    task = SharedTask(org_id=org.id, title="Qualify lead", responsible_department_id=dept.id)
    test_session.add(task)
    await test_session.commit()

    loaded = await test_session.get(SharedTask, task.id)
    assert loaded.status == "new"
    assert loaded.responsible_department_id == dept.id
