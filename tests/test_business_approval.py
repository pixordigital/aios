from typing import Any

import pytest

from aios.core.business_approval import (
    ApprovalDenied,
    InMemoryApprovalStore,
    require_approval_or_raise,
)


def test_create_request_pending():
    store = InMemoryApprovalStore()
    req = store.create_request(action="invoice.send", payload={"customer": "acme"})

    assert req.request_id
    assert req.token
    assert req.action == "invoice.send"
    assert req.payload == {"customer": "acme"}
    assert req.status == "pending"
    assert store.get(req.request_id) == req
    assert store.is_approved(req.request_id, req.token) is False


def test_approve_with_correct_token_ok():
    events: list[dict[str, Any]] = []
    store = InMemoryApprovalStore(audit_callback=events.append)
    req = store.create_request(action="payment.capture")

    decision = store.approve(req.request_id, req.token, reason="human ok")

    assert decision.request_id == req.request_id
    assert decision.approved is True
    assert decision.reason == "human ok"
    assert store.is_approved(req.request_id, req.token) is True
    assert store.get(req.request_id).status == "approved"
    assert any(
        e.get("event") == "business_approval.approved" and e.get("ok") is True
        for e in events
    )


def test_wrong_token_fails_closed():
    store = InMemoryApprovalStore()
    req = store.create_request(action="contract.sign")

    with pytest.raises(ApprovalDenied, match="token mismatch"):
        store.approve(req.request_id, "wrong-token")

    assert store.is_approved(req.request_id, req.token) is False
    assert store.is_approved(req.request_id, "wrong-token") is False


def test_reject_fails_closed():
    store = InMemoryApprovalStore()
    req = store.create_request(action="data.delete")

    decision = store.reject(req.request_id, req.token, reason="no")

    assert decision.approved is False
    assert store.is_approved(req.request_id, req.token) is False
    with pytest.raises(ApprovalDenied, match="rejected"):
        store.approve(req.request_id, req.token)
    with pytest.raises(ApprovalDenied, match="status=rejected"):
        require_approval_or_raise(store, req.request_id, req.token)


def test_missing_request_fails_closed():
    events: list[dict[str, Any]] = []
    store = InMemoryApprovalStore(audit_callback=events.append)

    assert store.get("missing") is None
    assert store.is_approved("missing", "any") is False
    with pytest.raises(ApprovalDenied, match="not found"):
        store.approve("missing", "any")
    with pytest.raises(ApprovalDenied, match="not found"):
        require_approval_or_raise(store, "missing", "any")
    assert any(
        e.get("event") == "business_approval.denied" and e.get("reason") == "request not found"
        for e in events
    )


def test_audit_emitted_on_create_and_decisions():
    events: list[dict[str, Any]] = []
    store = InMemoryApprovalStore(audit_callback=events.append)
    req = store.create_request(action="bulk.send")
    store.reject(req.request_id, req.token, reason="risk")

    kinds = [e.get("event") for e in events]
    assert "business_approval.created" in kinds
    assert "business_approval.rejected" in kinds


def test_require_approval_or_raise_happy_path():
    store = InMemoryApprovalStore()
    req = store.create_request(action="invoice.send")
    store.approve(req.request_id, req.token)

    got = require_approval_or_raise(store, req.request_id, req.token)
    assert got.request_id == req.request_id
    assert got.status == "approved"
