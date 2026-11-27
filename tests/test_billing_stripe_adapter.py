from typing import Any

import pytest

from aios.core.adapters.billing_stripe import StripeBillingAdapter
from aios.core.business_execution import ExecutionDenied


def _cfg() -> dict[str, str]:
    return {"STRIPE_SECRET_KEY": "sk_test_sandbox_stub"}


def _payload(**overrides: Any) -> dict[str, Any]:
    base = {"customer_id": "cus_123", "amount_cents": 1000, "currency": "usd"}
    base.update(overrides)
    return base


def test_missing_config_fail_closed_not_configured():
    adapter = StripeBillingAdapter(approved=True, sandbox_mode=True, config={}, sender=lambda **_: {"id": "pi_1"})
    with pytest.raises(ExecutionDenied, match="not_configured"):
        adapter.execute(action="create_payment_intent", payload=_payload(), idempotency_key="idem-cfg")


def test_missing_approval_or_sandbox_mode_fail_closed():
    sender = lambda **_: {"id": "pi_1"}
    # approved but sandbox_mode off
    adapter = StripeBillingAdapter(approved=True, sandbox_mode=False, config=_cfg(), sender=sender)
    with pytest.raises(ExecutionDenied, match="sandbox_mode|not_configured"):
        adapter.execute(action="create_payment_intent", payload=_payload(), idempotency_key="idem-sandbox")
    # sandbox_mode on but not approved
    adapter2 = StripeBillingAdapter(approved=False, sandbox_mode=True, config=_cfg(), sender=sender)
    with pytest.raises(ExecutionDenied, match="approval|not_configured"):
        adapter2.execute(action="create_payment_intent", payload=_payload(), idempotency_key="idem-approval")


def test_idempotency_required():
    adapter = StripeBillingAdapter(approved=True, sandbox_mode=True, config=_cfg(), sender=lambda **_: {"id": "pi_1"})
    with pytest.raises(ExecutionDenied, match="idempotency_key required"):
        adapter.execute(action="create_payment_intent", payload=_payload(), idempotency_key="")


def test_no_real_sender_fail_closed():
    adapter = StripeBillingAdapter(approved=True, sandbox_mode=True, config=_cfg(), sender=None)
    with pytest.raises(ExecutionDenied, match="sender required|no real Stripe"):
        adapter.execute(action="create_payment_intent", payload=_payload(), idempotency_key="idem-nosender")


def test_sandbox_sender_returns_structured_stub_result_and_audits():
    calls: list[dict[str, Any]] = []

    def sender(**kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        return {"id": "pi_sandbox_1", "status": "requires_capture"}

    adapter = StripeBillingAdapter(approved=True, sandbox_mode=True, config=_cfg(), sender=sender)
    result = adapter.execute(
        action="create_payment_intent",
        payload=_payload(),
        idempotency_key="idem-ok",
    )

    assert result.ok is True
    assert result.adapter == "billing_stripe"
    assert result.action == "create_payment_intent"
    assert result.idempotency_key == "idem-ok"
    assert result.status == "sandbox_stub"
    assert result.data["sandbox"] is True
    assert result.data["stub"] is True
    assert result.data["provider"] == "stripe"
    assert result.data["sender_result"]["id"] == "pi_sandbox_1"
    assert len(calls) == 1
    assert calls[0]["action"] == "create_payment_intent"
    assert calls[0]["idempotency_key"] == "idem-ok"

    audit_blob = str(adapter.audit) + str(result.data.get("audit"))
    assert "billing_stripe.start" in audit_blob
    assert "billing_stripe.result" in audit_blob
