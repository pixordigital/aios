"""Contract/e-sign adapter stub (sandbox/fail-closed, no real provider calls)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from aios.core.business_execution import AuditCallback, ExecutionDenied, ExecutionResult

_ALLOWED_ACTIONS = {
    "create_envelope",
    "get_envelope",
    "send_envelope",
    "void_envelope",
    "list_envelopes",
}


def _cfg_get(config: dict[str, Any], *keys: str) -> str:
    for key in keys:
        val = config.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if text:
            return text
    return ""


@dataclass
class ContractEsignAdapter:
    """ExecutionAdapter-compatible contract/e-sign stub.

    Fail-closed by default. No real provider SDK/HTTP calls. Sandbox/test mode
    requires explicit approval, sandbox_mode, config, and injected sender.
    """

    name: str = "contract_esign"
    approved: bool = False
    sandbox_mode: bool = False
    config: dict[str, Any] = field(default_factory=dict)
    sender: Callable[..., Any] | None = None
    audit_callback: AuditCallback | None = None
    audit: list[dict[str, Any]] = field(default_factory=list)

    def _record(self, event: dict[str, Any]) -> None:
        payload = dict(event)
        self.audit.append(payload)
        if self.audit_callback is not None:
            self.audit_callback(dict(payload))

    def _deny(self, *, action: str, idempotency_key: str, reason: str, status: str = "denied") -> ExecutionDenied:
        self._record(
            {
                "event": "contract_esign.denied",
                "adapter": self.name,
                "action": action,
                "idempotency_key": idempotency_key,
                "ok": False,
                "status": status,
                "reason": reason,
            }
        )
        return ExecutionDenied(reason)

    def _configured(self) -> bool:
        key = _cfg_get(self.config, "CONTRACT_ESIGN_API_KEY", "contract_esign_api_key", "api_key")
        return bool(key)

    def execute(self, *, action: str, payload: dict[str, Any], idempotency_key: str) -> ExecutionResult:
        action_name = str(action or "").strip()
        key = str(idempotency_key or "").strip()
        data = dict(payload or {})

        if action_name not in _ALLOWED_ACTIONS:
            raise self._deny(action=action_name, idempotency_key=key, reason=f"unsupported action: {action_name}")
        if not key:
            raise self._deny(action=action_name, idempotency_key=key, reason="idempotency_key required")
        if not self._configured():
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason="not_configured: CONTRACT_ESIGN_API_KEY required",
                status="not_configured",
            )
        if not bool(self.approved) or not bool(self.sandbox_mode):
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason="not_configured: contract_esign requires explicit approval and sandbox_mode",
                status="not_configured",
            )
        if self.sender is None:
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason="not_configured: sandbox sender required (no real provider calls)",
                status="not_configured",
            )

        self._record(
            {
                "event": "contract_esign.start",
                "adapter": self.name,
                "action": action_name,
                "idempotency_key": key,
                "ok": None,
                "sandbox": True,
            }
        )
        sender_result = self.sender(action=action_name, payload=dict(data), idempotency_key=key)
        result = ExecutionResult(
            ok=True,
            adapter=self.name,
            action=action_name,
            idempotency_key=key,
            status="sandbox_stub",
            detail="sandbox stub executed; no real contract/e-sign call made",
            data={
                "sandbox": True,
                "stub": True,
                "provider": "contract_esign",
                "action": action_name,
                "sender_result": sender_result,
            },
        )
        self._record(
            {
                "event": "contract_esign.result",
                "adapter": self.name,
                "action": action_name,
                "idempotency_key": key,
                "ok": True,
                "status": result.status,
            }
        )
        result.data["audit"] = list(self.audit)
        return result
