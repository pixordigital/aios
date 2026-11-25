"""Fail-closed safety/governance gate for business side effects.

All side effects must pass this gate before execution. Unknown/missing policy
data denies by default.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_HITL = "require_hitl"


@dataclass(frozen=True)
class SideEffectAction:
    """Describes a side effect the business wants to take."""

    action: str
    org_id: str | None = None
    actor_id: str | None = None
    idempotency_key: str | None = None
    # Spend controls
    spend_amount: float = 0.0
    spend_cap: float | None = None
    # Rate controls
    rate_count: int = 0
    rate_limit: int | None = None
    # Risk flags
    has_pii: bool = False
    external_commit: bool = False
    # Approval
    approval_token: str | None = None
    approved: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SafetyEvaluation:
    decision: PolicyDecision
    reasons: tuple[str, ...]
    audit_record: dict[str, Any]

    @property
    def allowed(self) -> bool:
        return self.decision == PolicyDecision.ALLOW

    @property
    def denied(self) -> bool:
        return self.decision == PolicyDecision.DENY

    @property
    def requires_hitl(self) -> bool:
        return self.decision == PolicyDecision.REQUIRE_HITL


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BusinessSafetyGate:
    """Uniform side-effect policy gate. Fail-closed by default."""

    def __init__(
        self,
        *,
        audit_emitter: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._audit_emitter = audit_emitter
        self.audit_records: list[dict[str, Any]] = []

    def _emit_audit(self, record: dict[str, Any]) -> None:
        self.audit_records.append(record)
        if self._audit_emitter is not None:
            try:
                self._audit_emitter(record)
            except Exception:
                logger.exception("business safety audit emitter failed")

    def evaluate(self, action: SideEffectAction) -> SafetyEvaluation:
        """Evaluate action against policy. Fail-closed on unknown/missing data."""
        reasons: list[str] = []
        decision = PolicyDecision.ALLOW

        def deny(reason: str) -> None:
            nonlocal decision
            reasons.append(reason)
            decision = PolicyDecision.DENY

        def require_hitl(reason: str) -> None:
            nonlocal decision
            reasons.append(reason)
            if decision != PolicyDecision.DENY:
                decision = PolicyDecision.REQUIRE_HITL

        # Fail-closed: action and required identity/binding must be present.
        if action is None:
            deny("missing_action")
        else:
            action_name = str(getattr(action, "action", "") or "").strip()
            org_id = str(getattr(action, "org_id", "") or "").strip()
            idempotency_key = str(getattr(action, "idempotency_key", "") or "").strip()
            approval_token = str(getattr(action, "approval_token", "") or "").strip()
            approved = bool(getattr(action, "approved", False))

            if not action_name:
                deny("missing_action_name")
            if not org_id:
                deny("missing_org_id")
            if not idempotency_key:
                deny("missing_idempotency_key")

            # Spend cap: deny when over cap; fail-closed when cap unknown but spend claimed.
            spend_amount = float(getattr(action, "spend_amount", 0.0) or 0.0)
            spend_cap = getattr(action, "spend_cap", None)
            if spend_amount < 0:
                deny("invalid_spend_amount")
            elif spend_amount > 0 and spend_cap is None:
                deny("missing_spend_cap")
            elif spend_cap is not None:
                try:
                    cap_val = float(spend_cap)
                except Exception:
                    deny("invalid_spend_cap")
                    cap_val = None
                if cap_val is not None and cap_val < 0:
                    deny("invalid_spend_cap")
                elif cap_val is not None and spend_amount > cap_val:
                    deny("spend_over_cap")

            # Rate limit: deny when exceeded or misconfigured.
            rate_count = int(getattr(action, "rate_count", 0) or 0)
            rate_limit = getattr(action, "rate_limit", None)
            if rate_count < 0:
                deny("invalid_rate_count")
            if rate_limit is not None:
                try:
                    limit_val = int(rate_limit)
                except Exception:
                    deny("invalid_rate_limit")
                    limit_val = None
                if limit_val is not None and limit_val <= 0:
                    deny("invalid_rate_limit")
                elif limit_val is not None and rate_count >= limit_val:
                    deny("rate_limit_exceeded")

            # PII flag: require HITL unless explicitly approved.
            if bool(getattr(action, "has_pii", False)):
                require_hitl("pii_requires_hitl")

            # External commit: require HITL unless explicitly approved.
            if bool(getattr(action, "external_commit", False)):
                require_hitl("external_commit_requires_hitl")

            # Explicit approval can satisfy HITL requirements, never deny reasons.
            has_approval = approved and bool(approval_token)
            if has_approval and decision == PolicyDecision.REQUIRE_HITL:
                reasons.append("approval_token_accepted")
                decision = PolicyDecision.ALLOW
            elif decision == PolicyDecision.REQUIRE_HITL and (approved or approval_token):
                # Partial/invalid approval is fail-closed.
                deny("invalid_approval")

        audit_record: dict[str, Any] = {
            "event": "business_safety.evaluate",
            "ts": _now_iso(),
            "action": str(getattr(action, "action", "") or "") if action is not None else "",
            "org_id": str(getattr(action, "org_id", "") or "") if action is not None else "",
            "actor_id": str(getattr(action, "actor_id", "") or "") if action is not None else "",
            "idempotency_key": str(getattr(action, "idempotency_key", "") or "") if action is not None else "",
            "decision": decision.value,
            "reasons": list(reasons),
            "external_commit": bool(getattr(action, "external_commit", False)) if action is not None else False,
            "has_pii": bool(getattr(action, "has_pii", False)) if action is not None else False,
            "spend_amount": float(getattr(action, "spend_amount", 0.0) or 0.0) if action is not None else 0.0,
            "spend_cap": getattr(action, "spend_cap", None) if action is not None else None,
            "approved": bool(getattr(action, "approved", False)) if action is not None else False,
        }
        self._emit_audit(audit_record)

        if decision == PolicyDecision.DENY:
            logger.warning("business safety denied: action=%s reasons=%s", audit_record["action"], reasons)
        elif decision == PolicyDecision.REQUIRE_HITL:
            logger.info("business safety hitl required: action=%s reasons=%s", audit_record["action"], reasons)
        else:
            logger.info("business safety allowed: action=%s", audit_record["action"])

        return SafetyEvaluation(decision=decision, reasons=tuple(reasons), audit_record=audit_record)
