from __future__ import annotations

from types import SimpleNamespace

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
    "billing_stripe",
    "accounting_erp",
    "fiscal_provider",
    "contract_esign",
    "payroll_provider",
    "tax_fiscal",
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


def test_typed_settings_csv_approves_only_with_config():
    sent: list[dict] = []
    settings = SimpleNamespace(
        execution_approved_adapters="email_resend",
        resend_api_key="rk-test",
        resend_from_email="sandbox@aios.local",
    )
    registry = build_business_execution_registry(
        settings=settings,
        sandbox_senders={"email_resend": lambda **kw: sent.append(kw) or {"id": "1"}},
    )

    email = registry.get("email_resend")
    assert email is not None and email.approved is True

    result = registry.execute(
        adapter="email_resend",
        action="send_email",
        payload={"to": "u@example.test", "subject": "s", "body": "b"},
        idempotency_key="idem-csv-ok",
    )
    assert result.ok is True
    assert len(sent) == 1

    with pytest.raises(ExecutionDenied, match="not approved"):
        registry.execute(
            adapter="whatsapp_evolution",
            action="send_text",
            payload={"recipient": "5511", "org_id": "org1", "approved": True, "text": "hi"},
            idempotency_key="idem-wa-denied",
        )


def test_per_adapter_flag_denied_when_missing_config():
    settings = SimpleNamespace(execution_adapter_email_resend_approved=True)
    registry = build_business_execution_registry(settings=settings)

    email = registry.get("email_resend")
    assert email is not None
    assert email.approved is False
    assert registry.missing_config.get("email_resend") == [
        "AIOS_RESEND_API_KEY",
        "AIOS_RESEND_FROM_EMAIL",
    ]

    with pytest.raises(ExecutionDenied, match="not approved"):
        registry.execute(
            adapter="email_resend",
            action="send_email",
            payload={"to": "u@example.test", "subject": "s", "body": "b"},
            idempotency_key="idem-missing-config",
        )


def test_calcom_approval_uses_event_type_id_and_reports_missing():
    settings = SimpleNamespace(
        execution_adapter_calendar_calcom_approved=True,
        calcom_api_key="cal-key",
        calcom_event_type_id=42,
        # missing webhook secret
    )
    registry = build_business_execution_registry(settings=settings)
    cal = registry.get("calendar_calcom")
    assert cal is not None
    assert cal.approved is False
    assert registry.missing_config.get("calendar_calcom") == ["AIOS_CALCOM_WEBHOOK_SECRET"]

    settings_ok = SimpleNamespace(
        execution_approved_adapters="calendar_calcom",
        calcom_api_key="cal-key",
        calcom_event_type_id=42,
        calcom_webhook_secret="whsec",
    )
    registry_ok = build_business_execution_registry(
        settings=settings_ok,
        sandbox_senders={"calendar_calcom": SimpleNamespace(availability=lambda **_: {"ok": True, "slots": []})},
    )
    cal_ok = registry_ok.get("calendar_calcom")
    assert cal_ok is not None and cal_ok.approved is True
