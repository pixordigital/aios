"""Fail-closed WhatsApp adapter backed by Evolution API config.

No real HTTP send by default. Inject `sender` for sandbox/tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from aios.core.business_execution import AuditCallback, ExecutionResult

logger = logging.getLogger(__name__)

SenderCallable = Callable[..., Any]
ALLOWED_ACTIONS = {"send_text", "send_template"}


def _audit(callback: AuditCallback | None, event: dict[str, Any]) -> None:
    payload = dict(event)
    payload.setdefault("adapter", "whatsapp_evolution")
    logger.info("whatsapp_evolution.audit %s", payload)
    if callback is not None:
        callback(payload)


def _fail(
    *,
    action: str,
    idempotency_key: str,
    reason: str,
    status: str = "denied",
    audit_callback: AuditCallback | None = None,
    extra: dict[str, Any] | None = None,
) -> ExecutionResult:
    event = {
        "event": "whatsapp_evolution.denied",
        "action": action,
        "idempotency_key": idempotency_key,
        "ok": False,
        "reason": reason,
        "status": status,
    }
    if extra:
        event.update(extra)
    _audit(audit_callback, event)
    return ExecutionResult(
        ok=False,
        adapter="whatsapp_evolution",
        action=action,
        idempotency_key=idempotency_key,
        status=status,
        detail=reason,
        data={"reason": reason},
    )


@dataclass
class EvolutionWhatsAppAdapter:
    """ExecutionAdapter-compatible WhatsApp wrapper with fail-closed guards."""

    name: str = "whatsapp_evolution"
    approved: bool = False
    server_url: str | None = None
    api_key: str | None = None
    sender: SenderCallable | None = None
    audit_callback: AuditCallback | None = None
    _seen_idempotency_keys: set[str] = field(default_factory=set, repr=False)

    def _configured(self) -> bool:
        # Explicit values (even empty) override settings; None means "use settings".
        if self.server_url is not None or self.api_key is not None:
            url = str(self.server_url or "").strip()
            key = str(self.api_key or "").strip()
            return bool(url and key)
        try:
            from aios.config import settings

            url = str(getattr(settings, "evolution_server_url", "") or "").strip()
            key = str(getattr(settings, "evolution_api_key", "") or "").strip()
        except Exception:
            return False
        return bool(url and key)

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
        recipient = str(data.get("recipient") or data.get("to") or "").strip()
        org_id = str(data.get("org_id") or "").strip()
        approved = data.get("approved") is True

        base_extra = {"recipient": recipient, "org_id": org_id}

        if not key:
            return _fail(
                action=action_name,
                idempotency_key=key,
                reason="idempotency_key required",
                status="denied",
                audit_callback=self.audit_callback,
                extra=base_extra,
            )

        if action_name not in ALLOWED_ACTIONS:
            return _fail(
                action=action_name,
                idempotency_key=key,
                reason=f"unsupported action: {action_name}",
                status="denied",
                audit_callback=self.audit_callback,
                extra=base_extra,
            )

        if not recipient:
            return _fail(
                action=action_name,
                idempotency_key=key,
                reason="recipient required",
                status="denied",
                audit_callback=self.audit_callback,
                extra=base_extra,
            )

        if not org_id:
            return _fail(
                action=action_name,
                idempotency_key=key,
                reason="org_id required",
                status="denied",
                audit_callback=self.audit_callback,
                extra=base_extra,
            )

        if not self._configured():
            return _fail(
                action=action_name,
                idempotency_key=key,
                reason="whatsapp_evolution not_configured: missing Evolution url/key",
                status="not_configured",
                audit_callback=self.audit_callback,
                extra=base_extra,
            )

        if not self.approved or not approved:
            return _fail(
                action=action_name,
                idempotency_key=key,
                reason="external send requires approval",
                status="denied",
                audit_callback=self.audit_callback,
                extra=base_extra,
            )

        if key in self._seen_idempotency_keys:
            _audit(
                self.audit_callback,
                {
                    "event": "whatsapp_evolution.idempotent_replay",
                    "action": action_name,
                    "idempotency_key": key,
                    "ok": True,
                    "recipient": recipient,
                    "org_id": org_id,
                },
            )
            return ExecutionResult(
                ok=True,
                adapter=self.name,
                action=action_name,
                idempotency_key=key,
                status="idempotent_replay",
                detail="duplicate idempotency_key replayed",
                data={"recipient": recipient, "org_id": org_id, "replay": True},
            )

        _audit(
            self.audit_callback,
            {
                "event": "whatsapp_evolution.start",
                "action": action_name,
                "idempotency_key": key,
                "ok": None,
                "recipient": recipient,
                "org_id": org_id,
            },
        )

        if self.sender is None:
            return _fail(
                action=action_name,
                idempotency_key=key,
                reason="no sender configured; fail closed",
                status="not_configured",
                audit_callback=self.audit_callback,
                extra=base_extra,
            )

        try:
            send_result = self.sender(
                action=action_name,
                payload=data,
                idempotency_key=key,
                recipient=recipient,
                org_id=org_id,
            )
        except Exception as exc:
            _audit(
                self.audit_callback,
                {
                    "event": "whatsapp_evolution.error",
                    "action": action_name,
                    "idempotency_key": key,
                    "ok": False,
                    "recipient": recipient,
                    "org_id": org_id,
                    "reason": str(exc),
                },
            )
            return ExecutionResult(
                ok=False,
                adapter=self.name,
                action=action_name,
                idempotency_key=key,
                status="error",
                detail=str(exc),
                data={"recipient": recipient, "org_id": org_id},
            )

        self._seen_idempotency_keys.add(key)
        result_data = {"recipient": recipient, "org_id": org_id}
        if isinstance(send_result, dict):
            result_data.update(send_result)

        result = ExecutionResult(
            ok=True,
            adapter=self.name,
            action=action_name,
            idempotency_key=key,
            status="ok",
            detail="sent",
            data=result_data,
        )
        _audit(
            self.audit_callback,
            {
                "event": "whatsapp_evolution.result",
                "action": action_name,
                "idempotency_key": key,
                "ok": True,
                "recipient": recipient,
                "org_id": org_id,
                "status": result.status,
            },
        )
        return result
