from __future__ import annotations

import pytest

from aios.core.adapters.registry import build_business_execution_registry
from aios.core.business_execution import ExecutionDenied


EXPECTED_ADAPTERS = {
    "crm_internal",
    "whatsapp_evolution",
    "email_resend",
    "calendar_calcom",
    "calendar_google",
    "fulfillment_service",
}


def test_default_registry_registered_but_not_approved():
    registry = build_business_execution_registry()

    for name in EXPECTED_ADAPTERS:
        adapter = registry.get(name)
        assert adapter is not None, f"missing adapter: {name}"
        assert getattr(adapter, "approved", False) is False, f"{name} should be unapproved by default"

    with pytest.raises(ExecutionDenied, match="adapter not approved"):
        registry.execute(
            adapter="email_resend",
            action="send_email",
            payload={"to": "a@b.test", "subject": "hi", "body": "hello"},
            idempotency_key="idem-default-denied",
        )


def test_sandbox_sender_and_approved_allows_execute():
    sent: list[dict] = []

    def sandbox_sender(*, action, payload, idempotency_key):
        sent.append({"action": action, "payload": payload, "idempotency_key": idempotency_key})
        return {"id": "sandbox-msg-1"}

    registry = build_business_execution_registry(
        approved_adapters=["email_resend"],
        sandbox_senders={"email_resend": sandbox_sender},
    )

    adapter = registry.get("email_resend")
    assert adapter is not None
    assert adapter.approved is True

    result = registry.execute(
        adapter="email_resend",
        action="send_email",
        payload={"to": "user@example.test", "subject": "Sandbox", "body": "hello"},
        idempotency_key="idem-sandbox-ok",
    )

    assert result.ok is True
    assert result.adapter == "email_resend"
    assert result.status == "ok"
    assert len(sent) == 1
    assert sent[0]["idempotency_key"] == "idem-sandbox-ok"


def test_calcom_present_as_primary_calendar():
    registry = build_business_execution_registry()

    cal = registry.get("calendar_calcom")
    assert cal is not None
    assert cal.name == "calendar_calcom"
    assert "cal" in cal.__class__.__name__.lower()

    # Primary calendar present; optional google also registered.
    assert registry.get("calendar_google") is not None
