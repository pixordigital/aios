"""Resend email adapter skeleton (sandbox/fail-closed, no real HTTP)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from aios.core.business_execution import ExecutionDenied, ExecutionResult


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
class ResendEmailAdapter:
    """ExecutionAdapter-compatible Resend email sender.

    Fail-closed: missing config/approval/idempotency/required fields denies.
    No real HTTP; inject `sender` for sandbox/testing.
    """

    name: str = "email_resend"
    approved: bool = False
    config: dict[str, Any] = field(default_factory=dict)
    sender: Callable[..., Any] | None = None
    audit: list[dict[str, Any]] = field(default_factory=list)

    def _deny(self, *, action: str, idempotency_key: str, reason: str) -> ExecutionDenied:
        record = {
            "event": "email_resend.denied",
            "adapter": self.name,
            "action": action,
            "idempotency_key": idempotency_key,
            "ok": False,
            "reason": reason,
        }
        self.audit.append(record)
        return ExecutionDenied(reason)

    def _audit(self, record: dict[str, Any]) -> None:
        self.audit.append(dict(record))

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

        if action_name != "send_email":
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason=f"unsupported action: {action_name}",
            )

        if not key:
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason="idempotency_key required",
            )

        api_key = _cfg_get(self.config, "RESEND_API_KEY", "resend_api_key", "api_key")
        from_email = _cfg_get(self.config, "from", "from_email", "sender")
        if not api_key or not from_email:
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason="not_configured: RESEND_API_KEY and from required",
            )

        # HITL approval required for external send - fail closed.
        if not bool(self.approved):
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason="hitl_approval_required",
            )

        to = data.get("to")
        subject = data.get("subject")
        body = data.get("body")
        template = data.get("template")
        if not to:
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason="to required",
            )
        if not str(subject or "").strip():
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason="subject required",
            )
        if not str(body or "").strip() and not str(template or "").strip():
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason="body or template required",
            )

        self._audit(
            {
                "event": "email_resend.start",
                "adapter": self.name,
                "action": action_name,
                "idempotency_key": key,
                "ok": None,
            }
        )

        if self.sender is None:
            raise self._deny(
                action=action_name,
                idempotency_key=key,
                reason="not_configured: sender required (no real HTTP)",
            )

        send_payload = {
            "to": to,
            "subject": subject,
            "body": body,
            "template": template,
            "from": from_email,
        }
        sender_result = self.sender(
            action=action_name,
            payload=send_payload,
            idempotency_key=key,
        )

        result = ExecutionResult(
            ok=True,
            adapter=self.name,
            action=action_name,
            idempotency_key=key,
            status="ok",
            detail="sandbox_sent",
            data={
                "to": to,
                "subject": subject,
                "from": from_email,
                "sender_result": sender_result,
            },
        )
        self._audit(
            {
                "event": "email_resend.result",
                "adapter": self.name,
                "action": action_name,
                "idempotency_key": key,
                "ok": True,
                "status": result.status,
            }
        )
        result.data["audit"] = list(self.audit)
        return result
