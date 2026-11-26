"""Service-as-Software fulfillment adapter.

Generic, configurable scaffold. No real external provisioning; side effects
run through an injected sandbox handler. Fail closed on missing config,
required fields, or missing approval for irreversible actions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from aios.core.business_execution import ExecutionDenied, ExecutionResult

AuditCallback = Callable[[dict[str, Any]], None]
SandboxHandler = Callable[[dict[str, Any]], dict[str, Any] | None]

IRREVERSIBLE_ACTIONS = frozenset({"deliver", "cancel"})
ACTIONS = ("provision", "start", "deliver", "accept", "cancel")


@dataclass
class ServiceFulfillmentAdapter:
    """ExecutionAdapter-compatible fulfillment scaffold.

    Config fields make intent explicit; unset/incomplete config fails closed.
    """

    name: str = "fulfillment_service"
    approved: bool = False
    configured: bool = False
    steps: list[dict[str, Any]] = field(default_factory=list)
    sandbox_handler: SandboxHandler | None = None
    audit_callback: AuditCallback | None = None
    audit_log: list[dict[str, Any]] = field(default_factory=list)
    _seen_keys: set[str] = field(default_factory=set, init=False, repr=False)

    def _audit(self, event: dict[str, Any]) -> None:
        payload = dict(event)
        payload.setdefault("adapter", self.name)
        self.audit_log.append(payload)
        if self.audit_callback is not None:
            self.audit_callback(dict(payload))

    def _deny(self, *, action: str, idempotency_key: str, reason: str, **extra: Any) -> ExecutionDenied:
        self._audit(
            {
                "event": "fulfillment.denied",
                "action": action,
                "idempotency_key": idempotency_key,
                "ok": False,
                "reason": reason,
                **extra,
            }
        )
        return ExecutionDenied(reason)

    def _has_approval(self, payload: dict[str, Any]) -> bool:
        if payload.get("approved") is True:
            return True
        approval_id = payload.get("approval_id")
        return isinstance(approval_id, str) and bool(approval_id.strip())

    def _require_configured(self, action: str, key: str) -> None:
        if not self.configured or not self.steps or self.sandbox_handler is None:
            raise self._deny(
                action=action,
                idempotency_key=key,
                reason="fulfillment adapter not configured",
            )

    def execute(
        self,
        *,
        action: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> ExecutionResult:
        action_name = str(action or "").strip()
        key = str(idempotency_key or "").strip()
        data = dict(payload or {})
        org_id = str(data.get("org_id") or "").strip()
        service_case_id = str(data.get("service_case_id") or "").strip()

        if not key:
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason="idempotency_key required",
                org_id=org_id,
                service_case_id=service_case_id,
            )

        self._require_configured(action_name, key)

        if not org_id:
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason="org_id required",
                service_case_id=service_case_id,
            )
        if not service_case_id:
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason="service_case_id required",
                org_id=org_id,
            )
        if action_name not in ACTIONS:
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason=f"unsupported action: {action_name}",
                org_id=org_id,
                service_case_id=service_case_id,
            )
        if action_name in IRREVERSIBLE_ACTIONS and not self._has_approval(data):
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason=f"approval required for irreversible action: {action_name}",
                org_id=org_id,
                service_case_id=service_case_id,
            )

        if key in self._seen_keys:
            self._audit(
                {
                    "event": "fulfillment.idempotent_replay",
                    "action": action_name,
                    "idempotency_key": key,
                    "org_id": org_id,
                    "service_case_id": service_case_id,
                    "ok": True,
                }
            )
            return ExecutionResult(
                ok=True,
                adapter=self.name,
                action=action_name,
                idempotency_key=key,
                status="idempotent_replay",
                detail="duplicate idempotency_key replayed",
                data={"org_id": org_id, "service_case_id": service_case_id},
            )

        self._audit(
            {
                "event": "fulfillment.start",
                "action": action_name,
                "idempotency_key": key,
                "org_id": org_id,
                "service_case_id": service_case_id,
                "steps": [s.get("name", s.get("id", str(i))) for i, s in enumerate(self.steps)],
                "ok": None,
            }
        )

        try:
            handler_result = self.sandbox_handler(
                {
                    "action": action_name,
                    "payload": data,
                    "idempotency_key": key,
                    "org_id": org_id,
                    "service_case_id": service_case_id,
                    "steps": list(self.steps),
                }
            )
        except Exception as exc:
            self._audit(
                {
                    "event": "fulfillment.error",
                    "action": action_name,
                    "idempotency_key": key,
                    "org_id": org_id,
                    "service_case_id": service_case_id,
                    "ok": False,
                    "reason": str(exc),
                }
            )
            raise

        self._seen_keys.add(key)
        result_data = dict(handler_result) if isinstance(handler_result, dict) else {}
        result_data.setdefault("org_id", org_id)
        result_data.setdefault("service_case_id", service_case_id)
        result = ExecutionResult(
            ok=True,
            adapter=self.name,
            action=action_name,
            idempotency_key=key,
            status="ok",
            detail="sandbox fulfillment handler completed",
            data=result_data,
        )
        self._audit(
            {
                "event": "fulfillment.result",
                "action": action_name,
                "idempotency_key": key,
                "org_id": org_id,
                "service_case_id": service_case_id,
                "ok": True,
                "status": result.status,
            }
        )
        return result
