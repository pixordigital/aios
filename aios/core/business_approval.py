"""Fail-closed HITL approval flow for side-effectful business actions.

No action approved unless explicitly approved with matching request id+token.
All state transitions emit audit events.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

AuditCallback = Callable[[dict[str, Any]], None]


class ApprovalDenied(PermissionError):
    """Approval missing, rejected, or token mismatch (fail-closed)."""


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    token: str
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending | approved | rejected


@dataclass(frozen=True)
class ApprovalDecision:
    request_id: str
    approved: bool
    reason: str = ""


class InMemoryApprovalStore:
    """In-memory approval store. Fail-closed by default."""

    def __init__(self, *, audit_callback: AuditCallback | None = None) -> None:
        self._requests: dict[str, ApprovalRequest] = {}
        self._audit_callback = audit_callback

    def _audit(self, event: dict[str, Any]) -> None:
        payload = dict(event)
        logger.info("business_approval.audit %s", payload)
        if self._audit_callback is not None:
            self._audit_callback(payload)

    def create_request(
        self, *, action: str, payload: dict[str, Any] | None = None
    ) -> ApprovalRequest:
        action_name = str(action or "").strip()
        if not action_name:
            raise ValueError("action required")
        req = ApprovalRequest(
            request_id=uuid.uuid4().hex,
            token=uuid.uuid4().hex,
            action=action_name,
            payload=dict(payload or {}),
            status="pending",
        )
        self._requests[req.request_id] = req
        self._audit(
            {
                "event": "business_approval.created",
                "request_id": req.request_id,
                "action": req.action,
                "status": req.status,
                "ok": None,
            }
        )
        return req

    def get(self, request_id: str) -> ApprovalRequest | None:
        return self._requests.get(str(request_id or "").strip())

    def _resolve(self, request_id: str, token: str) -> ApprovalRequest:
        rid = str(request_id or "").strip()
        tok = str(token or "").strip()
        req = self._requests.get(rid)
        if req is None:
            self._audit(
                {
                    "event": "business_approval.denied",
                    "request_id": rid,
                    "ok": False,
                    "reason": "request not found",
                }
            )
            raise ApprovalDenied("approval request not found")
        if not tok or tok != req.token:
            self._audit(
                {
                    "event": "business_approval.denied",
                    "request_id": rid,
                    "action": req.action,
                    "ok": False,
                    "reason": "token mismatch",
                }
            )
            raise ApprovalDenied("approval token mismatch")
        return req

    def approve(self, request_id: str, token: str, *, reason: str = "") -> ApprovalDecision:
        req = self._resolve(request_id, token)
        if req.status == "rejected":
            self._audit(
                {
                    "event": "business_approval.denied",
                    "request_id": req.request_id,
                    "action": req.action,
                    "ok": False,
                    "reason": "request rejected",
                }
            )
            raise ApprovalDenied("approval request rejected")
        decided = ApprovalRequest(
            request_id=req.request_id,
            token=req.token,
            action=req.action,
            payload=dict(req.payload),
            status="approved",
        )
        self._requests[req.request_id] = decided
        decision = ApprovalDecision(request_id=req.request_id, approved=True, reason=str(reason or ""))
        self._audit(
            {
                "event": "business_approval.approved",
                "request_id": req.request_id,
                "action": req.action,
                "status": decided.status,
                "ok": True,
                "reason": decision.reason,
            }
        )
        return decision

    def reject(self, request_id: str, token: str, *, reason: str = "") -> ApprovalDecision:
        req = self._resolve(request_id, token)
        decided = ApprovalRequest(
            request_id=req.request_id,
            token=req.token,
            action=req.action,
            payload=dict(req.payload),
            status="rejected",
        )
        self._requests[req.request_id] = decided
        decision = ApprovalDecision(request_id=req.request_id, approved=False, reason=str(reason or ""))
        self._audit(
            {
                "event": "business_approval.rejected",
                "request_id": req.request_id,
                "action": req.action,
                "status": decided.status,
                "ok": False,
                "reason": decision.reason,
            }
        )
        return decision

    def is_approved(self, request_id: str, token: str) -> bool:
        rid = str(request_id or "").strip()
        tok = str(token or "").strip()
        req = self._requests.get(rid)
        if req is None:
            return False
        if not tok or tok != req.token:
            return False
        return req.status == "approved"


def require_approval_or_raise(
    store: InMemoryApprovalStore, request_id: str, token: str
) -> ApprovalRequest:
    """Fail-closed guard: raise ApprovalDenied unless explicitly approved with matching token."""
    rid = str(request_id or "").strip()
    tok = str(token or "").strip()
    req = store.get(rid)
    if req is None:
        store._audit(
            {
                "event": "business_approval.denied",
                "request_id": rid,
                "ok": False,
                "reason": "request not found",
            }
        )
        raise ApprovalDenied("approval request not found")
    if not tok or tok != req.token:
        store._audit(
            {
                "event": "business_approval.denied",
                "request_id": rid,
                "action": req.action,
                "ok": False,
                "reason": "token mismatch",
            }
        )
        raise ApprovalDenied("approval token mismatch")
    if req.status != "approved":
        store._audit(
            {
                "event": "business_approval.denied",
                "request_id": rid,
                "action": req.action,
                "status": req.status,
                "ok": False,
                "reason": "not approved",
            }
        )
        raise ApprovalDenied(f"approval required: status={req.status}")
    return req


__all__ = [
    "ApprovalDecision",
    "ApprovalDenied",
    "ApprovalRequest",
    "AuditCallback",
    "InMemoryApprovalStore",
    "require_approval_or_raise",
]
