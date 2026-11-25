"""Tests for uniform business side-effect safety gate."""

from aios.core.business_safety import (
    BusinessSafetyGate,
    PolicyDecision,
    SideEffectAction,
)


def _action(**kwargs):
    base = dict(
        action="send_invoice",
        org_id="org-1",
        actor_id="user-1",
        idempotency_key="idem-1",
        spend_amount=10.0,
        spend_cap=100.0,
        rate_count=0,
        rate_limit=100,
        has_pii=False,
        external_commit=False,
        approval_token=None,
        approved=False,
    )
    base.update(kwargs)
    return SideEffectAction(**base)


def test_missing_idempotency_denied():
    gate = BusinessSafetyGate()
    result = gate.evaluate(_action(idempotency_key=""))

    assert result.decision == PolicyDecision.DENY
    assert result.denied is True
    assert "missing_idempotency_key" in result.reasons


def test_external_commit_requires_hitl():
    gate = BusinessSafetyGate()
    result = gate.evaluate(_action(external_commit=True))

    assert result.decision == PolicyDecision.REQUIRE_HITL
    assert result.requires_hitl is True
    assert "external_commit_requires_hitl" in result.reasons


def test_spend_over_cap_denied():
    gate = BusinessSafetyGate()
    result = gate.evaluate(_action(spend_amount=150.0, spend_cap=100.0))

    assert result.decision == PolicyDecision.DENY
    assert result.denied is True
    assert "spend_over_cap" in result.reasons


def test_approved_action_allowed():
    gate = BusinessSafetyGate()
    result = gate.evaluate(
        _action(
            external_commit=True,
            approved=True,
            approval_token="approval-123",
        )
    )

    assert result.decision == PolicyDecision.ALLOW
    assert result.allowed is True
    assert "approval_token_accepted" in result.reasons


def test_audit_record_emitted():
    emitted = []
    gate = BusinessSafetyGate(audit_emitter=emitted.append)
    action = _action(action="charge_card", external_commit=True)

    result = gate.evaluate(action)

    assert len(emitted) == 1
    assert len(gate.audit_records) == 1
    record = gate.audit_records[0]
    assert record is result.audit_record
    assert record["event"] == "business_safety.evaluate"
    assert record["action"] == "charge_card"
    assert record["org_id"] == "org-1"
    assert record["idempotency_key"] == "idem-1"
    assert record["decision"] == result.decision.value
    assert "external_commit_requires_hitl" in record["reasons"]
    assert isinstance(record["ts"], str) and record["ts"]
