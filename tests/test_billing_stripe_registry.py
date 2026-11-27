from types import SimpleNamespace

import pytest

from aios.core.adapters.registry import build_business_execution_registry
from aios.core.business_execution import ExecutionDenied


def test_billing_stripe_default_unapproved_fail_closed():
    registry = build_business_execution_registry()
    adapter = registry.get("billing_stripe")
    assert adapter is not None
    assert adapter.approved is False

    with pytest.raises(ExecutionDenied, match="not approved"):
        registry.execute(
            adapter="billing_stripe",
            action="create_payment_intent",
            payload={"org_id": "org1", "amount_cents": 100},
            idempotency_key="idem-stripe-denied",
        )


def test_billing_stripe_requested_without_sandbox_mode_reports_missing_and_stays_unapproved():
    settings = SimpleNamespace(
        execution_adapter_billing_stripe_approved=True,
        stripe_secret_key="sk_test_123",
        stripe_sandbox_mode=False,
    )
    registry = build_business_execution_registry(settings=settings)
    adapter = registry.get("billing_stripe")
    assert adapter is not None
    assert adapter.approved is False
    assert "AIOS_STRIPE_SANDBOX_MODE/sandbox sender" in registry.missing_config.get("billing_stripe", [])


def test_billing_stripe_sandbox_sender_approved_executes_stub():
    sent: list[dict] = []

    def sandbox_sender(**kw):
        sent.append(dict(kw))
        return {"id": "pi_stub_1"}

    settings = SimpleNamespace(execution_approved_adapters="billing_stripe")
    registry = build_business_execution_registry(
        settings=settings,
        sandbox_senders={"billing_stripe": sandbox_sender},
    )
    adapter = registry.get("billing_stripe")
    assert adapter is not None
    assert adapter.approved is True
    assert getattr(adapter, "sandbox_mode", False) is True

    result = registry.execute(
        adapter="billing_stripe",
        action="create_payment_intent",
        payload={"org_id": "org1", "amount_cents": 1000, "currency": "usd"},
        idempotency_key="idem-stripe-ok",
    )

    assert result.ok is True
    assert result.status == "sandbox_stub"
    assert result.data["sandbox"] is True
    assert result.data["stub"] is True
    assert result.data["provider"] == "stripe"
    assert len(sent) == 1
    assert sent[0]["idempotency_key"] == "idem-stripe-ok"
