"""Accounting/ERP adapter stub (sandbox/fail-closed, no real sync)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from aios.core.business_execution import AuditCallback, ExecutionDenied, ExecutionResult

_ALLOWED_ACTIONS = {
    "sync_customer",
    "sync_invoice",
    "sync_payment",
    "push_ledger_entry",
    "get_sync_status",
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
class AccountingErpAdapter:
    """ExecutionAdapter-compatible accounting/ERP stub.

    Fail-closed by default. No real ERP/accounting calls, no money movement.
    For sandbox/test mode, inject `sender` and explicitly approve+configure.
    Returns structured sandbox/stub/not_configured results.
    """

    name: str = "accounting_erp"
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
                "event": "accounting_erp.denied",
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
        api_key = _cfg_get(self.config, "ACCOUNTING_ERP_API_KEY", "accounting_erp_api_key", "api_key")
        base_url = _cfg_get(self.config, "ACCOUNTING_ERP_BASE_URL", "accounting_erp_base_url", "base_url")
        return bool(api_key and base_url)

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

        if action_name not in _ALLOWED_ACTIONS:
            raise self._deny(action=action_name, idempotency_key=key, reason=f"unsupported action: {action_name}")
        if not key:
            raise self._deny(action=action_name, idempotency_key=key, reason="idempotency_key required")

        if not self._configured():
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason="not_configured: ACCOUNTING_ERP_API_KEY and ACCOUNTING_ERP_BASE_URL required",
                status="not_configured",
            )

        if not bool(self.approved) or not bool(self.sandbox_mode):
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason="not_configured: accounting_erp requires explicit approval and sandbox_mode",
                status="not_configured",
            )

        if self.sender is None:
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason="not_configured: sandbox sender required (no real ERP calls)",
                status="not_configured",
            )

        self._record(
            {
                "event": "accounting_erp.start",
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
            detail="sandbox stub executed; no real ERP/accounting call made",
            data={
                "sandbox": True,
                "stub": True,
                "provider": "accounting_erp",
                "action": action_name,
                "sender_result": sender_result,
            },
        )
        self._record(
            {
                "event": "accounting_erp.result",
                "adapter": self.name,
                "action": action_name,
                "idempotency_key": key,
                "ok": True,
                "status": result.status,
            }
        )
        result.data["audit"] = list(self.audit)
        return result
