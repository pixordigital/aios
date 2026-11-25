"""Fail-closed execution scaffold for running a business.

Additive scaffold only: no real integrations, no credentials. Side-effect
execution requires an explicitly configured and approved adapter plus an
idempotency key. All decisions emit an audit callback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

AuditCallback = Callable[[dict[str, Any]], None]


class ExecutionDenied(PermissionError):
    """Execution denied by fail-closed policy."""


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    adapter: str
    action: str
    idempotency_key: str
    status: str
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ExecutionAdapter(Protocol):
    """Adapter contract for business side effects.

    Real integrations must be explicitly configured and approved out of band.
    This scaffold does not ship credentials or live adapters.
    """

    name: str
    approved: bool

    def execute(
        self,
        *,
        action: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> ExecutionResult: ...


class ExecutionRegistry:
    """Registry of execution adapters with fail-closed enforcement."""

    def __init__(self, *, audit_callback: AuditCallback | None = None) -> None:
        self._adapters: dict[str, ExecutionAdapter] = {}
        self._audit_callback = audit_callback

    def register(self, adapter: ExecutionAdapter) -> None:
        name = str(getattr(adapter, "name", "") or "").strip()
        if not name:
            raise ValueError("adapter.name required")
        self._adapters[name] = adapter

    def get(self, name: str) -> ExecutionAdapter | None:
        return self._adapters.get(name)

    def _audit(self, event: dict[str, Any]) -> None:
        payload = dict(event)
        logger.info("business_execution.audit %s", payload)
        if self._audit_callback is not None:
            self._audit_callback(payload)

    def _deny(
        self,
        *,
        adapter: str,
        action: str,
        idempotency_key: str,
        reason: str,
    ) -> ExecutionDenied:
        self._audit(
            {
                "event": "business_execution.denied",
                "adapter": adapter,
                "action": action,
                "idempotency_key": idempotency_key,
                "ok": False,
                "reason": reason,
            }
        )
        return ExecutionDenied(reason)

    def execute(
        self,
        *,
        adapter: str,
        action: str,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        side_effect: bool = True,
    ) -> ExecutionResult:
        adapter_name = str(adapter or "").strip()
        action_name = str(action or "").strip()
        key = str(idempotency_key or "").strip()
        data = dict(payload or {})

        if not adapter_name:
            raise self._deny(
                adapter=adapter_name,
                action=action_name,
                idempotency_key=key,
                reason="adapter not configured",
            )

        if side_effect and not key:
            raise self._deny(
                adapter=adapter_name,
                action=action_name,
                idempotency_key=key,
                reason="idempotency_key required for side effects",
            )

        impl = self._adapters.get(adapter_name)
        if impl is None:
            raise self._deny(
                adapter=adapter_name,
                action=action_name,
                idempotency_key=key,
                reason=f"adapter not configured: {adapter_name}",
            )

        if not bool(getattr(impl, "approved", False)):
            raise self._deny(
                adapter=adapter_name,
                action=action_name,
                idempotency_key=key,
                reason=f"adapter not approved: {adapter_name}",
            )

        self._audit(
            {
                "event": "business_execution.start",
                "adapter": adapter_name,
                "action": action_name,
                "idempotency_key": key,
                "side_effect": side_effect,
                "ok": None,
            }
        )

        try:
            result = impl.execute(
                action=action_name,
                payload=data,
                idempotency_key=key,
            )
        except Exception as exc:
            self._audit(
                {
                    "event": "business_execution.error",
                    "adapter": adapter_name,
                    "action": action_name,
                    "idempotency_key": key,
                    "ok": False,
                    "reason": str(exc),
                }
            )
            raise

        if not isinstance(result, ExecutionResult):
            raise self._deny(
                adapter=adapter_name,
                action=action_name,
                idempotency_key=key,
                reason="adapter returned invalid result",
            )

        self._audit(
            {
                "event": "business_execution.result",
                "adapter": adapter_name,
                "action": action_name,
                "idempotency_key": key,
                "ok": result.ok,
                "status": result.status,
            }
        )
        return result
