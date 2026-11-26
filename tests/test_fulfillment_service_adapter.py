import pytest

from aios.core.adapters.fulfillment_service import ServiceFulfillmentAdapter
from aios.core.business_execution import ExecutionDenied


def _configured_adapter(handler=None):
    return ServiceFulfillmentAdapter(
        name="fulfillment_service",
        approved=True,
        configured=True,
        steps=[{"id": "review", "name": "Review"}, {"id": "deliver", "name": "Deliver"}],
        sandbox_handler=handler or (lambda ctx: {"sandbox": "ok", "action": ctx["action"]}),
    )


def _payload(**overrides):
    base = {
        "org_id": "org-1",
        "service_case_id": "case-1",
    }
    base.update(overrides)
    return base


def test_missing_config_fails_closed():
    adapter = ServiceFulfillmentAdapter(approved=True, configured=False)

    with pytest.raises(ExecutionDenied, match="not configured"):
        adapter.execute(
            action="provision",
            payload=_payload(),
            idempotency_key="idem-config-1",
        )

    assert any(e["event"] == "fulfillment.denied" for e in adapter.audit_log)


def test_deliver_without_approval_fails_closed():
    adapter = _configured_adapter()

    with pytest.raises(ExecutionDenied, match="approval required"):
        adapter.execute(
            action="deliver",
            payload=_payload(),
            idempotency_key="idem-deliver-1",
        )


def test_sandbox_handler_ok():
    calls = []

    def handler(ctx):
        calls.append(ctx)
        return {"receipt": "sandbox-receipt"}

    adapter = _configured_adapter(handler=handler)
    result = adapter.execute(
        action="provision",
        payload=_payload(customer="acme"),
        idempotency_key="idem-ok-1",
    )

    assert result.ok is True
    assert result.status == "ok"
    assert result.adapter == "fulfillment_service"
    assert result.action == "provision"
    assert result.idempotency_key == "idem-ok-1"
    assert result.data["org_id"] == "org-1"
    assert result.data["service_case_id"] == "case-1"
    assert result.data["receipt"] == "sandbox-receipt"
    assert len(calls) == 1
    assert calls[0]["action"] == "provision"
    assert calls[0]["service_case_id"] == "case-1"
    assert calls[0]["steps"][0]["id"] == "review"
    assert any(e["event"] == "fulfillment.result" and e["ok"] is True for e in adapter.audit_log)


def test_idempotency_required():
    adapter = _configured_adapter()

    with pytest.raises(ExecutionDenied, match="idempotency_key required"):
        adapter.execute(
            action="start",
            payload=_payload(),
            idempotency_key="",
        )
