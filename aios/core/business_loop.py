"""Minimal closed-loop business ops state machine.

States: lead->qualify->outreach->follow_up->close->invoice->delivery->support->retention.
Side-effectful transitions (outreach, invoice, delivery) require HITL approval.
Transitions are validated, auditable, and idempotent by idempotency_key.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

STATES = (
    "lead",
    "qualify",
    "outreach",
    "follow_up",
    "close",
    "invoice",
    "delivery",
    "support",
    "retention",
    "lost",
    "cancelled",
)

TERMINAL_STATES = frozenset({"retention", "lost", "cancelled"})
FAILURE_STATES = frozenset({"lost", "cancelled"})

# Allowed current -> target transitions. Fail closed: absent edge denied.
TRANSITIONS: dict[str, frozenset[str]] = {
    "lead": frozenset({"qualify", "lost", "cancelled"}),
    "qualify": frozenset({"outreach", "lost", "cancelled"}),
    "outreach": frozenset({"follow_up", "lost", "cancelled"}),
    "follow_up": frozenset({"close", "outreach", "lost", "cancelled"}),
    "close": frozenset({"invoice", "lost", "cancelled"}),
    "invoice": frozenset({"delivery", "lost", "cancelled"}),
    "delivery": frozenset({"support", "lost", "cancelled"}),
    "support": frozenset({"retention", "lost", "cancelled"}),
    "retention": frozenset(),
    "lost": frozenset(),
    "cancelled": frozenset(),
}

# Entering these states causes external/business side effects.
SIDE_EFFECTFUL_TARGETS = frozenset({"outreach", "invoice", "delivery"})


class BusinessLoopError(ValueError):
    """Base business loop error."""


class TransitionError(BusinessLoopError):
    """Invalid or denied transition."""


class ApprovalRequiredError(BusinessLoopError):
    """Side-effectful transition missing valid HITL approval."""


@dataclass
class BusinessCase:
    case_id: str
    org_id: str
    state: str = "lead"
    audit_log: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise BusinessLoopError(f"unknown state: {self.state}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(value: Any) -> str:
    return str(value or "").strip()


def is_side_effectful(target: str) -> bool:
    return _norm(target) in SIDE_EFFECTFUL_TARGETS


def can_transition(current: str, target: str) -> bool:
    cur = _norm(current)
    tgt = _norm(target)
    return tgt in TRANSITIONS.get(cur, frozenset())


def _find_idempotent_record(case: BusinessCase, *, idempotency_key: str) -> dict[str, Any] | None:
    for rec in case.audit_log:
        if rec.get("idempotency_key") == idempotency_key:
            return rec
    return None


def _require_approval(*, case: BusinessCase, target: str, idempotency_key: str, approved: bool, approved_by: str | None, approval_evidence: dict[str, Any] | None) -> str:
    if not approved:
        raise ApprovalRequiredError(f"HITL approval required for side-effect transition to {target}")
    approver = _norm(approved_by)
    if not approver:
        raise ApprovalRequiredError(f"HITL approver required for side-effect transition to {target}")
    evidence = approval_evidence if isinstance(approval_evidence, dict) else {}
    ev_key = _norm(evidence.get("idempotency_key"))
    if ev_key and ev_key != idempotency_key:
        raise ApprovalRequiredError("approval evidence idempotency_key mismatch")
    ev_case = _norm(evidence.get("case_id"))
    if ev_case and ev_case != case.case_id:
        raise ApprovalRequiredError("approval evidence case_id mismatch")
    ev_target = _norm(evidence.get("target"))
    if ev_target and ev_target != target:
        raise ApprovalRequiredError("approval evidence target mismatch")
    ev_org = _norm(evidence.get("org_id"))
    if ev_org and ev_org != case.org_id:
        raise ApprovalRequiredError("approval evidence org_id mismatch")
    return approver


def transition(
    case: BusinessCase,
    target: str,
    *,
    actor: str,
    idempotency_key: str,
    reason: str = "",
    approved: bool = False,
    approved_by: str | None = None,
    approval_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and apply a state transition.

    Fail-closed: unknown states/edges denied. Side-effectful targets require HITL.
    Idempotent: same (from,to,idempotency_key) returns existing audit record.
    """
    tgt = _norm(target)
    actor_n = _norm(actor)
    key = _norm(idempotency_key)
    if not actor_n:
        raise BusinessLoopError("actor required")
    if not key:
        raise BusinessLoopError("idempotency_key required")
    if case.state not in STATES:
        raise BusinessLoopError(f"unknown current state: {case.state}")
    if tgt not in STATES:
        raise BusinessLoopError(f"unknown target state: {tgt}")

    existing = _find_idempotent_record(case, idempotency_key=key)
    if existing is not None:
        if existing.get("to") == tgt and existing.get("from") == case.state or existing.get("to") == tgt:
            # Same idempotency key + same target = idempotent replay.
            if existing.get("from") != case.state and existing.get("to") == tgt:
                return existing
            return existing
        raise TransitionError(
            f"idempotency key conflict: {key} already used for {existing.get('from')} -> {existing.get('to')}"
        )

    if not can_transition(case.state, tgt):
        raise TransitionError(f"invalid transition {case.state} -> {tgt}")

    approver = None
    side_effectful = is_side_effectful(tgt)
    if side_effectful:
        approver = _require_approval(
            case=case,
            target=tgt,
            idempotency_key=key,
            approved=approved,
            approved_by=approved_by,
            approval_evidence=approval_evidence,
        )

    record = {
        "case_id": case.case_id,
        "org_id": case.org_id,
        "from": case.state,
        "to": tgt,
        "actor": actor_n,
        "reason": _norm(reason),
        "idempotency_key": key,
        "side_effectful": side_effectful,
        "approved_by": approver,
        "at": _now_iso(),
    }
    case.audit_log.append(record)
    case.state = tgt
    return record
