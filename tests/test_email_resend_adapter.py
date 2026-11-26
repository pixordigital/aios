from typing import Any

import pytest

from aios.core.adapters.email_resend import ResendEmailAdapter
from aios.core.business_execution import ExecutionDenied


def _cfg() -> dict[str, str]:
    return {"RESEND_API_KEY": "test-key", "from": "noreply@example.com"}


def _payload(**overrides: Any) -> dict[str, Any]:
    base = {
        "to": "user@example.com",
        "subject": "Hello",
        "body": "Hi there",
    }
    base.update(overrides)
    return base


def test_missing_config_fails_closed_not_configured():
    adapter = ResendEmailAdapter(approved=True, config={}, sender=lambda **_: {"id": "msg"})
    with pytest.raises(ExecutionDenied, match="not_configured"):
        adapter.execute(
            action="send_email",
            payload=_payload(),
            idempotency_key="idem-cfg",
        )


def test_missing_approval_fails_closed():
    adapter = ResendEmailAdapter(approved=False, config=_cfg(), sender=lambda **_: {"id": "msg"})
    with pytest.raises(ExecutionDenied, match="approval|hitl"):
        adapter.execute(
            action="send_email",
            payload=_payload(),
            idempotency_key="idem-approval",
        )


def test_idempotency_required():
    adapter = ResendEmailAdapter(approved=True, config=_cfg(), sender=lambda **_: {"id": "msg"})
    with pytest.raises(ExecutionDenied, match="idempotency_key required"):
        adapter.execute(
            action="send_email",
            payload=_payload(),
            idempotency_key="",
        )


def test_approved_sandbox_sender_ok_and_audit():
    calls: list[dict[str, Any]] = []

    def sender(**kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        return {"id": "sandbox-msg-1"}

    adapter = ResendEmailAdapter(approved=True, config=_cfg(), sender=sender)
    result = adapter.execute(
        action="send_email",
        payload=_payload(),
        idempotency_key="idem-ok",
    )

    assert result.ok is True
    assert result.adapter == "email_resend"
    assert result.action == "send_email"
    assert result.idempotency_key == "idem-ok"
    assert len(calls) == 1
    assert calls[0]["payload"]["to"] == "user@example.com"
    assert calls[0]["idempotency_key"] == "idem-ok"

    # Audit record present on adapter and/or result.
    audit_records = list(getattr(adapter, "audit", []) or [])
    result_audit = result.data.get("audit") if isinstance(result.data, dict) else None
    assert audit_records or result_audit
    audit_blob = str(audit_records) + str(result_audit)
    assert "send_email" in audit_blob
    assert "idem-ok" in audit_blob
