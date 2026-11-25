"""Integration-style scope guards: fail-closed/no-fake-integration scaffolds."""

import pytest

from aios.core.business_execution import ExecutionDenied, ExecutionRegistry
from aios.core.business_loop import ApprovalRequiredError, BusinessCase, transition
from aios.core.business_safety import BusinessSafetyGate, PolicyDecision, SideEffectAction
from aios.core.kpi_instrumentation import NOT_INSTRUMENTED, clear_sources, record_reading


@pytest.fixture(autouse=True)
def _clean_kpi_sources():
    clear_sources()
    yield
    clear_sources()


def test_execution_registry_no_adapter_denies():
    registry = ExecutionRegistry()

    with pytest.raises(ExecutionDenied, match="not configured"):
        registry.execute(
            adapter="missing_adapter",
            action="invoice.create",
            payload={"customer": "acme"},
            idempotency_key="idem-scope-1",
        )


def test_business_safety_gate_denies_missing_idempotency_and_approval_for_external_commit():
    gate = BusinessSafetyGate()

    missing_idempotency = gate.evaluate(
        SideEffectAction(
            action="send_invoice",
            org_id="org-1",
            idempotency_key="",
            spend_amount=10.0,
            spend_cap=100.0,
            external_commit=True,
        )
    )
    assert missing_idempotency.decision == PolicyDecision.DENY
    assert "missing_idempotency_key" in missing_idempotency.reasons

    missing_approval = gate.evaluate(
        SideEffectAction(
            action="send_invoice",
            org_id="org-1",
            idempotency_key="idem-scope-2",
            spend_amount=10.0,
            spend_cap=100.0,
            external_commit=True,
            approved=False,
            approval_token=None,
        )
    )
    assert missing_approval.decision == PolicyDecision.REQUIRE_HITL
    assert missing_approval.allowed is False
    assert "external_commit_requires_hitl" in missing_approval.reasons


def test_kpi_instrumentation_record_reading_unknown_source_not_instrumented():
    reading = record_reading(
        name="mrr",
        value=1200.0,
        unit="usd",
        source="unknown_billing_db",
    )

    assert reading.instrumented is False
    assert reading.status == NOT_INSTRUMENTED
    assert reading.value is None
    assert reading.source == "unknown_billing_db"


def test_business_loop_requires_approval_for_side_effect_transitions():
    case = BusinessCase(case_id="case-1", org_id="org-1")
    transition(case, "qualify", actor="agent:a1", idempotency_key="scope-q1")

    with pytest.raises(ApprovalRequiredError):
        transition(
            case,
            "outreach",
            actor="agent:a1",
            idempotency_key="scope-outreach-no-approval",
        )

    assert case.state == "qualify"
