import pytest

from aios.core.business_loop import (
    ApprovalRequiredError,
    BusinessCase,
    SIDE_EFFECTFUL_TARGETS,
    TransitionError,
    transition,
)


def test_valid_transition_appends_audit_record():
    case = BusinessCase(case_id="c1", org_id="o1")
    rec = transition(case, "qualify", actor="agent:a1", idempotency_key="k1", reason="qualified")

    assert case.state == "qualify"
    assert len(case.audit_log) == 1
    assert rec["from"] == "lead"
    assert rec["to"] == "qualify"
    assert rec["actor"] == "agent:a1"
    assert rec["idempotency_key"] == "k1"
    assert rec["side_effectful"] is False


def test_invalid_transition_rejected_fail_closed():
    case = BusinessCase(case_id="c1", org_id="o1")
    with pytest.raises(TransitionError, match="invalid transition lead -> close"):
        transition(case, "close", actor="agent:a1", idempotency_key="k-bad")

    assert case.state == "lead"
    assert case.audit_log == []


@pytest.mark.parametrize("target", sorted(SIDE_EFFECTFUL_TARGETS))
def test_side_effectful_transition_requires_approval(target):
    # Walk deterministically to the state just before target.
    case = BusinessCase(case_id="c1", org_id="o1")
    path = ["qualify", "outreach", "follow_up", "close", "invoice", "delivery"]
    for i, step in enumerate(path):
        if step == target:
            break
        prev = "lead" if i == 0 else path[i - 1]
        approved = step in SIDE_EFFECTFUL_TARGETS
        transition(
            case,
            step,
            actor="agent:a1",
            idempotency_key=f"setup-{step}",
            approved=approved,
            approved_by="human:u1" if approved else None,
            approval_evidence={"case_id": "c1", "org_id": "o1", "target": step, "idempotency_key": f"setup-{step}"} if approved else None,
        )
        assert case.state == step

    before = case.state
    audit_len = len(case.audit_log)
    with pytest.raises(ApprovalRequiredError):
        transition(case, target, actor="agent:a1", idempotency_key=f"k-{target}")

    assert case.state == before
    assert len(case.audit_log) == audit_len

    rec = transition(
        case,
        target,
        actor="agent:a1",
        idempotency_key=f"k-{target}",
        approved=True,
        approved_by="human:u1",
        approval_evidence={"case_id": "c1", "org_id": "o1", "target": target, "idempotency_key": f"k-{target}"},
    )
    assert case.state == target
    assert rec["side_effectful"] is True
    assert rec["approved_by"] == "human:u1"


def test_idempotent_duplicate_transition_returns_same_audit_record():
    case = BusinessCase(case_id="c1", org_id="o1")
    first = transition(case, "qualify", actor="agent:a1", idempotency_key="dup-1")
    second = transition(case, "qualify", actor="agent:a1", idempotency_key="dup-1")

    assert second is first
    assert case.state == "qualify"
    assert len(case.audit_log) == 1
