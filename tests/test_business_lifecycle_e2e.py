"""E2E business lifecycle simulation - deterministic, sandbox-only.

Covers chained lifecycle:
lead -> qualify -> outreach -> follow_up -> close -> invoice -> delivery -> support -> retention

Includes fail-closed denial, idempotent replay/no-duplicate side effect,
human reject+override, and failure injection+resume.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock

import pytest

from aios.core.adapters.registry import build_business_execution_registry
from aios.core.business_approval import (
    ApprovalDenied,
    InMemoryApprovalStore,
    require_approval_or_raise,
)
from aios.core.business_execution import ExecutionDenied, ExecutionResult
from aios.core.business_loop import (
    ApprovalRequiredError,
    BusinessCase,
    transition,
)


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


def _counting_sender(log: list[dict[str, Any]], name: str, *, fail_times: int = 0):
    state = {"calls": 0}

    def _sender(*args: Any, **kwargs: Any) -> dict[str, Any]:
        state["calls"] += 1
        entry: dict[str, Any] = {"sender": name, "call": state["calls"]}
        if args:
            entry["args"] = args
        entry.update(kwargs)
        log.append(entry)
        if state["calls"] <= fail_times:
            raise RuntimeError(f"injected failure {state['calls']} for {name}")
        return {"ok": True, "sandbox": True, "sender": name, "call": state["calls"]}

    _sender.state = state  # type: ignore[attr-defined]
    return _sender


def _counting_cal_client(log: list[dict[str, Any]], *, fail_times: int = 0):
    state = {"calls": 0}

    class _Client:
        def create(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
            state["calls"] += 1
            log.append(
                {
                    "sender": "calendar_calcom",
                    "action": "create",
                    "call": state["calls"],
                    "payload": dict(payload),
                    "idempotency_key": idempotency_key,
                }
            )
            if state["calls"] <= fail_times:
                raise RuntimeError(f"injected failure {state['calls']} for calendar_calcom")
            return {"ok": True, "status": "ok", "booking_id": f"sandbox-booking-{state['calls']}"}

    _Client.state = state  # type: ignore[attr-defined]
    return _Client()


def _approve(store: InMemoryApprovalStore, *, action: str, payload: dict[str, Any], reason: str):
    req = store.create_request(action=action, payload=payload)
    decision = store.approve(req.request_id, req.token, reason=reason)
    approved_req = require_approval_or_raise(store, req.request_id, req.token)
    return req, decision, approved_req


def _transition_with_hitl(
    case: BusinessCase,
    target: str,
    *,
    actor: str,
    idempotency_key: str,
    reason: str,
    store: InMemoryApprovalStore,
):
    """Create HITL approval for side-effectful transitions, then transition."""
    before = case.state
    side_effectful = target in {"outreach", "invoice", "delivery"}
    approved = False
    approved_by = None
    evidence = None
    req = None
    if side_effectful:
        req = store.create_request(action=f"transition.{target}", payload={"case_id": case.case_id, "target": target})
        store.approve(req.request_id, req.token, reason=f"approve {target}")
        approved_req = require_approval_or_raise(store, req.request_id, req.token)
        approved = True
        approved_by = f"human:{approved_req.request_id[:8]}"
        evidence = {
            "case_id": case.case_id,
            "org_id": case.org_id,
            "target": target,
            "idempotency_key": idempotency_key,
            "approval_request_id": approved_req.request_id,
        }
    rec = transition(
        case,
        target,
        actor=actor,
        idempotency_key=idempotency_key,
        reason=reason,
        approved=approved,
        approved_by=approved_by,
        approval_evidence=evidence,
    )
    return rec, req, before


def _build_sandbox_registry(audit_events: list[dict[str, Any]], sender_log: list[dict[str, Any]], *, fail: dict[str, int] | None = None):
    fail = fail or {}
    db = _fake_db()
    sandbox_senders = {
        "crm_internal": _counting_sender(sender_log, "crm_internal", fail_times=fail.get("crm_internal", 0)),
        "calendar_calcom": _counting_cal_client(sender_log, fail_times=fail.get("calendar_calcom", 0)),
        "email_resend": _counting_sender(sender_log, "email_resend", fail_times=fail.get("email_resend", 0)),
        "whatsapp_evolution": _counting_sender(sender_log, "whatsapp_evolution", fail_times=fail.get("whatsapp_evolution", 0)),
        "fulfillment_service": _counting_sender(sender_log, "fulfillment_service", fail_times=fail.get("fulfillment_service", 0)),
    }
    registry = build_business_execution_registry(
        db=db,
        audit_callback=audit_events.append,
        sandbox_senders=sandbox_senders,
        approved_adapters=[
            "crm_internal",
            "calendar_calcom",
            "email_resend",
            "whatsapp_evolution",
            "fulfillment_service",
        ],
    )
    return registry, sandbox_senders


LIFECYCLE_STEPS: list[dict[str, Any]] = [
    {
        "target": "qualify",
        "adapter": "crm_internal",
        "action": "upsert_contact",
        "payload": {"org_id": "org-e2e", "email": "lead@e2e.test", "name": "Lead E2E"},
    },
    {
        "target": "outreach",
        "adapter": "email_resend",
        "action": "send_email",
        "payload": {"to": "lead@e2e.test", "subject": "Outreach", "body": "Hello"},
    },
    {
        "target": "follow_up",
        "adapter": "whatsapp_evolution",
        "action": "send_text",
        "payload": {
            "recipient": "5511999999999",
            "org_id": "org-e2e",
            "approved": True,
            "text": "Follow up",
        },
    },
    {
        "target": "close",
        "adapter": "crm_internal",
        "action": "upsert_deal",
        "payload": {
            "org_id": "org-e2e",
            "lead_email": "lead@e2e.test",
            "lead_name": "Lead E2E",
            "stage": "won",
            "value": 1200.0,
        },
    },
    {
        "target": "invoice",
        "adapter": "fulfillment_service",
        "action": "provision",
        "payload": {"org_id": "org-e2e", "service_case_id": "case-e2e", "approved": True},
    },
    {
        "target": "delivery",
        "adapter": "fulfillment_service",
        "action": "deliver",
        "payload": {
            "org_id": "org-e2e",
            "service_case_id": "case-e2e",
            "approved": True,
            "approval_id": "approval-delivery-e2e",
        },
    },
    {
        "target": "support",
        "adapter": "crm_internal",
        "action": "add_activity",
        "payload": {"org_id": "org-e2e", "summary": "Support ticket opened and resolved"},
    },
    {
        "target": "retention",
        "adapter": "whatsapp_evolution",
        "action": "send_text",
        "payload": {
            "recipient": "5511999999999",
            "org_id": "org-e2e",
            "approved": True,
            "text": "Retention check-in",
        },
    },
]


def test_chained_business_lifecycle_happy_path_sandbox() -> None:
    audit_events: list[dict[str, Any]] = []
    sender_log: list[dict[str, Any]] = []
    store = InMemoryApprovalStore(audit_callback=audit_events.append)
    registry, _senders = _build_sandbox_registry(audit_events, sender_log)
    case = BusinessCase(case_id="case-e2e", org_id="org-e2e")

    for i, step in enumerate(LIFECYCLE_STEPS):
        target = step["target"]
        adapter = step["adapter"]
        action = step["action"]
        payload = dict(step["payload"])
        idem = f"e2e-{case.case_id}-{target}-{i}"

        rec, _approval_req, before = _transition_with_hitl(
            case,
            target,
            actor="agent:e2e",
            idempotency_key=f"state-{idem}",
            reason=f"advance to {target}",
            store=store,
        )
        assert rec["from"] == before
        assert rec["to"] == target
        assert case.state == target

        result = registry.execute(
            adapter=adapter,
            action=action,
            payload=payload,
            idempotency_key=idem,
        )
        assert result.ok is True
        assert result.adapter == adapter
        assert result.action == action
        assert result.idempotency_key == idem

    assert case.state == "retention"
    assert len(case.audit_log) == len(LIFECYCLE_STEPS)
    # Side-effectful targets must carry HITL evidence in state audit.
    for rec in case.audit_log:
        if rec["side_effectful"]:
            assert rec["approved_by"]
    exec_results = [e for e in audit_events if e.get("event") == "business_execution.result" and e.get("ok") is True]
    assert len(exec_results) == len(LIFECYCLE_STEPS)
    assert any(e.get("event") == "business_approval.approved" for e in audit_events)
    # Sandbox-injected adapters that emit sender logs must have been called.
    logged_senders = {e.get("sender") for e in sender_log}
    assert "email_resend" in logged_senders
    assert "whatsapp_evolution" in logged_senders
    assert "fulfillment_service" in logged_senders


def test_fail_closed_denial_blocks_side_effect() -> None:
    audit_events: list[dict[str, Any]] = []
    sender_log: list[dict[str, Any]] = []
    store = InMemoryApprovalStore(audit_callback=audit_events.append)
    # default registry: adapters registered but unapproved
    registry = build_business_execution_registry(audit_callback=audit_events.append)
    case = BusinessCase(case_id="case-deny", org_id="org-e2e")

    # 1) State transition to side-effectful target denied without HITL approval.
    transition(case, "qualify", actor="agent:e2e", idempotency_key="deny-qualify", reason="qualified")
    with pytest.raises(ApprovalRequiredError):
        transition(
            case,
            "outreach",
            actor="agent:e2e",
            idempotency_key="deny-transition",
        )
    assert case.state == "qualify"

    # 2) Execution denied when adapter not approved, even with HITL approval.
    req = store.create_request(action="email_resend.send_email", payload={"to": "x@y.test"})
    store.approve(req.request_id, req.token, reason="approved but adapter not approved")
    require_approval_or_raise(store, req.request_id, req.token)
    with pytest.raises(ExecutionDenied, match="adapter not approved"):
        registry.execute(
            adapter="email_resend",
            action="send_email",
            payload={"to": "x@y.test", "subject": "Nope", "body": "Nope"},
            idempotency_key="deny-exec",
        )

    # 3) Adapter-level denial: configured/approved adapter but missing HITL payload approval.
    sandbox_registry, _ = _build_sandbox_registry(audit_events, sender_log)
    result = sandbox_registry.execute(
        adapter="whatsapp_evolution",
        action="send_text",
        payload={
            "recipient": "5511999999999",
            "org_id": "org-e2e",
            "approved": False,  # fail closed
            "text": "should not send",
        },
        idempotency_key="deny-wa",
    )
    assert result.ok is False
    assert result.status == "denied"
    assert not any(e.get("sender") == "whatsapp_evolution" for e in sender_log)
    assert any(e.get("event") == "business_execution.denied" for e in audit_events)


def test_idempotent_replay_no_duplicate_side_effect() -> None:
    audit_events: list[dict[str, Any]] = []
    sender_log: list[dict[str, Any]] = []
    store = InMemoryApprovalStore(audit_callback=audit_events.append)
    registry, senders = _build_sandbox_registry(audit_events, sender_log)
    case = BusinessCase(case_id="case-idem", org_id="org-e2e")

    # State transition idempotency: same key returns same audit record, no duplicate.
    rec1, _, _ = _transition_with_hitl(
        case, "qualify", actor="agent:e2e", idempotency_key="state-qualify", reason="q", store=store
    )
    rec2, _, _ = _transition_with_hitl(
        case, "qualify", actor="agent:e2e", idempotency_key="state-qualify", reason="q", store=store
    )
    assert rec2 is rec1
    assert case.state == "qualify"
    assert len(case.audit_log) == 1

    # Side-effect idempotency: WhatsApp adapter dedupes by idempotency_key.
    payload = {
        "recipient": "5511999999999",
        "org_id": "org-e2e",
        "approved": True,
        "text": "idempotent hello",
    }
    r1 = registry.execute(
        adapter="whatsapp_evolution",
        action="send_text",
        payload=payload,
        idempotency_key="wa-idem-1",
    )
    r2 = registry.execute(
        adapter="whatsapp_evolution",
        action="send_text",
        payload=payload,
        idempotency_key="wa-idem-1",
    )
    assert r1.ok is True
    assert r2.ok is True
    assert r2.status == "idempotent_replay"
    wa_calls = [e for e in sender_log if e.get("sender") == "whatsapp_evolution"]
    assert len(wa_calls) == 1, "sandbox sender must not be called twice for same idempotency key"

    # Fulfillment adapter also dedupes by idempotency_key.
    ff_payload = {
        "org_id": "org-e2e",
        "service_case_id": "case-idem",
        "approved": True,
    }
    f1 = registry.execute(
        adapter="fulfillment_service",
        action="provision",
        payload=ff_payload,
        idempotency_key="ff-idem-1",
    )
    f2 = registry.execute(
        adapter="fulfillment_service",
        action="provision",
        payload=ff_payload,
        idempotency_key="ff-idem-1",
    )
    assert f1.ok is True and f1.status == "ok"
    assert f2.ok is True and f2.status == "idempotent_replay"
    ff_calls = [e for e in sender_log if e.get("sender") == "fulfillment_service"]
    assert len(ff_calls) == 1


def test_human_reject_then_override() -> None:
    audit_events: list[dict[str, Any]] = []
    sender_log: list[dict[str, Any]] = []
    store = InMemoryApprovalStore(audit_callback=audit_events.append)
    registry, _ = _build_sandbox_registry(audit_events, sender_log)
    case = BusinessCase(case_id="case-override", org_id="org-e2e")

    # Move to qualify (non-side-effectful) so outreach is next side-effectful step.
    transition(case, "qualify", actor="agent:e2e", idempotency_key="q-1", reason="qualified")
    assert case.state == "qualify"

    payload = {"to": "lead@e2e.test", "subject": "Outreach", "body": "Hi"}
    action = "email_resend.send_email"

    # Human rejects first request.
    rejected = store.create_request(action=action, payload=payload)
    decision = store.reject(rejected.request_id, rejected.token, reason="bad timing")
    assert decision.approved is False
    assert store.is_approved(rejected.request_id, rejected.token) is False
    with pytest.raises(ApprovalDenied):
        require_approval_or_raise(store, rejected.request_id, rejected.token)

    # Rejected request cannot be approved later (fail closed).
    with pytest.raises(ApprovalDenied, match="rejected"):
        store.approve(rejected.request_id, rejected.token, reason="changed mind")

    # No side effect executed under rejected approval: HITL gate prevents execution.
    with pytest.raises(ApprovalDenied):
        require_approval_or_raise(store, rejected.request_id, rejected.token)
    assert not any(e.get("sender") == "email_resend" for e in sender_log)

    # Human override: create new approval request, approve, then execute.
    override_req = store.create_request(action=action, payload=payload)
    store.approve(override_req.request_id, override_req.token, reason="override after review")
    approved_req = require_approval_or_raise(store, override_req.request_id, override_req.token)

    rec = transition(
        case,
        "outreach",
        actor="agent:e2e",
        idempotency_key="outreach-override-1",
        reason="human override",
        approved=True,
        approved_by=f"human:{approved_req.request_id[:8]}",
        approval_evidence={
            "case_id": case.case_id,
            "org_id": case.org_id,
            "target": "outreach",
            "idempotency_key": "outreach-override-1",
            "approval_request_id": approved_req.request_id,
        },
    )
    assert rec["to"] == "outreach"
    result = registry.execute(
        adapter="email_resend",
        action="send_email",
        payload=payload,
        idempotency_key="email-override-1",
    )
    assert result.ok is True
    assert case.state == "outreach"
    assert any(e.get("event") == "business_approval.rejected" for e in audit_events)
    assert any(e.get("event") == "business_approval.approved" for e in audit_events)
    assert sum(1 for e in sender_log if e.get("sender") == "email_resend") == 1


def test_failure_injection_and_resume() -> None:
    audit_events: list[dict[str, Any]] = []
    sender_log: list[dict[str, Any]] = []
    # Inject failure on first fulfillment handler call, then succeed.
    registry, _ = _build_sandbox_registry(audit_events, sender_log, fail={"fulfillment_service": 1})
    store = InMemoryApprovalStore(audit_callback=audit_events.append)
    case = BusinessCase(case_id="case-resume", org_id="org-e2e")

    # Advance deterministically to invoice (side-effectful).
    for target, idem in [
        ("qualify", "q"),
        ("outreach", "o"),
        ("follow_up", "f"),
        ("close", "c"),
    ]:
        _transition_with_hitl(
            case, target, actor="agent:e2e", idempotency_key=f"resume-{idem}", reason=target, store=store
        )
    assert case.state == "close"

    # HITL approve invoice transition and execution.
    inv_req = store.create_request(action="transition.invoice", payload={"case_id": case.case_id})
    store.approve(inv_req.request_id, inv_req.token, reason="approve invoice")
    approved_inv = require_approval_or_raise(store, inv_req.request_id, inv_req.token)
    transition(
        case,
        "invoice",
        actor="agent:e2e",
        idempotency_key="resume-invoice-state",
        reason="invoice",
        approved=True,
        approved_by=f"human:{approved_inv.request_id[:8]}",
        approval_evidence={
            "case_id": case.case_id,
            "org_id": case.org_id,
            "target": "invoice",
            "idempotency_key": "resume-invoice-state",
        },
    )
    assert case.state == "invoice"

    payload = {"org_id": "org-e2e", "service_case_id": "case-resume", "approved": True}

    # First execution attempt fails due to injected handler failure.
    with pytest.raises(RuntimeError, match="injected failure 1 for fulfillment_service"):
        registry.execute(
            adapter="fulfillment_service",
            action="provision",
            payload=payload,
            idempotency_key="resume-invoice-exec",
        )

    ff_calls = [e for e in sender_log if e.get("sender") == "fulfillment_service"]
    assert len(ff_calls) == 1
    assert any(
        e.get("event") == "business_execution.error" and e.get("adapter") == "fulfillment_service"
        for e in audit_events
    )

    # Resume: retry same operation; handler succeeds on second call.
    resumed = registry.execute(
        adapter="fulfillment_service",
        action="provision",
        payload=payload,
        idempotency_key="resume-invoice-exec-retry",
    )
    assert resumed.ok is True
    assert resumed.status == "ok"
    ff_calls = [e for e in sender_log if e.get("sender") == "fulfillment_service"]
    assert len(ff_calls) == 2, "resume should execute after injected failure"

    # Lifecycle can continue after resume.
    _transition_with_hitl(
        case, "delivery", actor="agent:e2e", idempotency_key="resume-delivery", reason="deliver", store=store
    )
    delivery_result = registry.execute(
        adapter="fulfillment_service",
        action="deliver",
        payload={
            "org_id": "org-e2e",
            "service_case_id": "case-resume",
            "approved": True,
            "approval_id": "approval-delivery-resume",
        },
        idempotency_key="resume-delivery-exec",
    )
    assert delivery_result.ok is True
    assert case.state == "delivery"


@pytest.mark.skipif(
    not os.getenv("AIOS_RUN_CREDENTIAL_SANDBOX_E2E"),
    reason="credentialed/external sandbox not configured; set AIOS_RUN_CREDENTIAL_SANDBOX_E2E=1 with sandbox creds",
)
def test_credentialed_external_sandbox_e2e() -> None:
    """Placeholder for real credentialed sandbox runs.

    Skipped by default: no real creds/network in deterministic CI/local runs.
    When enabled, this should exercise provider sandbox accounts only.
    """
    pytest.fail("credentialed sandbox E2E not implemented in this deterministic test slice")
