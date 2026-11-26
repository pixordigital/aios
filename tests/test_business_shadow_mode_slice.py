"""End-to-end shadow-mode integration test - first live-safe business slice.

Covers CRM internal + Cal.com primary + Resend + Evolution, all sandbox,
HITL-gated. No real network/DB.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from aios.core.adapters.registry import build_business_execution_registry
from aios.core.business_approval import (
    ApprovalDenied,
    InMemoryApprovalStore,
    require_approval_or_raise,
)
from aios.core.business_execution import ExecutionDenied


def _fake_db(existing: Any = None) -> MagicMock:
    db = MagicMock()
    q = MagicMock()
    q.filter_by.return_value = q
    q.first.return_value = existing
    db.query.return_value = q
    db.add.return_value = None
    db.flush.return_value = None
    db.get.return_value = None
    return db


def _sandbox_sender(log: list[dict[str, Any]], name: str):
    def _sender(**kwargs: Any) -> dict[str, Any]:
        entry = {"sender": name, **kwargs}
        log.append(entry)
        return {"ok": True, "sandbox": True, "sender": name}

    return _sender


def _cal_sandbox_client(log: list[dict[str, Any]]):
    class _Client:
        def create(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
            log.append({"sender": "calendar_calcom", "payload": payload, "idempotency_key": idempotency_key})
            return {"ok": True, "status": "ok", "booking_id": "sandbox-booking-1"}

        def availability(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
            log.append({"sender": "calendar_calcom", "payload": payload, "idempotency_key": idempotency_key})
            return {"ok": True, "status": "ok", "slots": []}

    return _Client()


CASES = [
    {
        "name": "crm_internal",
        "adapter": "crm_internal",
        "action": "upsert_contact",
        "payload": {"org_id": "org-shadow-1", "email": "lead@shadow.test", "name": "Shadow Lead"},
    },
    {
        "name": "calendar_calcom",
        "adapter": "calendar_calcom",
        "action": "create",
        # CalCom adapter requires booking-change approval in payload.
        "payload": {
            "approved": True,
            "start": "2026-12-01T10:00:00Z",
            "end": "2026-12-01T10:30:00Z",
            "attendee_email": "lead@shadow.test",
        },
    },
    {
        "name": "email_resend",
        "adapter": "email_resend",
        "action": "send_email",
        "payload": {"to": "lead@shadow.test", "subject": "Shadow", "body": "Shadow-mode test"},
    },
    {
        "name": "whatsapp_evolution",
        "adapter": "whatsapp_evolution",
        "action": "send_text",
        "payload": {
            "recipient": "5511999999999",
            "org_id": "org-shadow-1",
            "approved": True,
            "text": "Shadow-mode hello",
        },
    },
]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_shadow_mode_slice_hitl_gated_sandbox(case: dict[str, Any]) -> None:
    audit_events: list[dict[str, Any]] = []
    sender_log: list[dict[str, Any]] = []
    db = _fake_db()

    sandbox_senders = {
        "crm_internal": _sandbox_sender(sender_log, "crm_internal"),
        "calendar_calcom": _cal_sandbox_client(sender_log),
        "email_resend": _sandbox_sender(sender_log, "email_resend"),
        "whatsapp_evolution": _sandbox_sender(sender_log, "whatsapp_evolution"),
    }
    approved = ["crm_internal", "calendar_calcom", "email_resend", "whatsapp_evolution"]

    registry = build_business_execution_registry(
        db=db,
        audit_callback=audit_events.append,
        sandbox_senders=sandbox_senders,
        approved_adapters=approved,
    )
    store = InMemoryApprovalStore(audit_callback=audit_events.append)

    adapter_name = case["adapter"]
    action = case["action"]
    payload = dict(case["payload"])
    idempotency_key = f"shadow-{adapter_name}-{action}"

    # Registry adapters approved/configured in this sandbox slice.
    adapter = registry.get(adapter_name)
    assert adapter is not None, f"missing adapter: {adapter_name}"
    assert getattr(adapter, "approved", False) is True

    # HITL: create approval request, must be denied/not approved before approval.
    req = store.create_request(action=f"{adapter_name}.{action}", payload=payload)
    assert req.status == "pending"
    assert store.is_approved(req.request_id, req.token) is False
    with pytest.raises(ApprovalDenied):
        require_approval_or_raise(store, req.request_id, req.token)

    # Approve and gate execution.
    decision = store.approve(req.request_id, req.token, reason="shadow-mode test")
    assert decision.approved is True
    approved_req = require_approval_or_raise(store, req.request_id, req.token)
    assert approved_req.status == "approved"
    assert approved_req.request_id == req.request_id

    # Execute only after HITL approval.
    result = registry.execute(
        adapter=adapter_name,
        action=action,
        payload=payload,
        idempotency_key=idempotency_key,
    )

    assert result.ok is True
    assert result.adapter == adapter_name
    assert result.action == action
    assert result.idempotency_key == idempotency_key
    assert result.status

    # Audit events captured for approval flow and execution.
    assert any(e.get("event") == "business_approval.created" for e in audit_events)
    assert any(e.get("event") == "business_approval.approved" for e in audit_events)
    assert any(
        e.get("event") == "business_execution.start" and e.get("adapter") == adapter_name
        for e in audit_events
    )
    assert any(
        e.get("event") == "business_execution.result"
        and e.get("adapter") == adapter_name
        and e.get("ok") is True
        for e in audit_events
    )


def test_shadow_mode_slice_registry_denies_unapproved_before_hitl() -> None:
    """Defense-in-depth: unapproved registry adapter fails closed even if HITL approved."""
    audit_events: list[dict[str, Any]] = []
    store = InMemoryApprovalStore(audit_callback=audit_events.append)
    registry = build_business_execution_registry(audit_callback=audit_events.append)  # default: all unapproved

    req = store.create_request(action="email_resend.send_email", payload={"to": "x@y.test"})
    store.approve(req.request_id, req.token)
    require_approval_or_raise(store, req.request_id, req.token)

    with pytest.raises(ExecutionDenied):
        registry.execute(
            adapter="email_resend",
            action="send_email",
            payload={"to": "x@y.test", "subject": "s", "body": "b"},
            idempotency_key="shadow-unapproved",
        )

    assert any(e.get("event") == "business_execution.denied" for e in audit_events)
