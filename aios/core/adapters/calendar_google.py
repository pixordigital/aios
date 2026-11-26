"""Google Calendar execution adapter skeleton. Fail-closed, no real creds/network."""
from __future__ import annotations

from typing import Any

from aios.core.business_execution import ExecutionResult

_BOOKING_CHANGES = frozenset({"create", "reschedule", "cancel"})
_ACTIONS = frozenset({"availability", *_BOOKING_CHANGES})


def _booking_approved(payload: dict[str, Any]) -> bool:
    if payload.get("approved") is True:
        return True
    approval_id = str(payload.get("approval_id") or "").strip()
    if approval_id:
        return True
    approval = payload.get("approval")
    return isinstance(approval, dict) and bool(approval.get("approved") or approval.get("id"))


class GoogleCalendarAdapter:
    """ExecutionAdapter-compatible Google Calendar skeleton.

    Config required: credentials + calendar_id. Inject `client` for sandbox/tests.
    Booking changes (create/reschedule/cancel) require idempotency_key + approval.
    """

    name = "google_calendar"

    def __init__(
        self,
        *,
        credentials: Any = None,
        calendar_id: str | None = None,
        client: Any = None,
        approved: bool = True,
    ) -> None:
        self.credentials = credentials
        self.calendar_id = str(calendar_id or "").strip() or None
        self.client = client
        self._approved = bool(approved)

    @property
    def configured(self) -> bool:
        return bool(self.credentials) and bool(self.calendar_id)

    @property
    def approved(self) -> bool:
        # Adapter-level approval; registry gates on this. Config still fail-closed in execute.
        return bool(self._approved) and self.configured

    def _deny(self, action: str, idempotency_key: str, reason: str) -> ExecutionResult:
        return ExecutionResult(
            ok=False,
            adapter=self.name,
            action=action,
            idempotency_key=idempotency_key,
            status="denied",
            detail=reason,
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

        if not self.configured:
            return self._deny(action_name, key, "not configured: credentials/calendar_id required")
        if action_name not in _ACTIONS:
            return self._deny(action_name, key, f"unsupported action: {action_name}")

        if action_name in _BOOKING_CHANGES:
            if not key:
                return self._deny(action_name, key, "idempotency_key required for booking changes")
            if not _booking_approved(data):
                return self._deny(action_name, key, "approval required for external booking changes")

        if self.client is None:
            return self._deny(action_name, key, "not configured: client unavailable")

        try:
            handler = getattr(self.client, action_name, None)
            if not callable(handler):
                return self._deny(action_name, key, f"client missing action: {action_name}")
            result = handler(payload=data, idempotency_key=key)
        except Exception as exc:
            return ExecutionResult(
                ok=False,
                adapter=self.name,
                action=action_name,
                idempotency_key=key,
                status="error",
                detail=str(exc),
            )

        if isinstance(result, ExecutionResult):
            return result
        if isinstance(result, dict):
            return ExecutionResult(
                ok=bool(result.get("ok", True)),
                adapter=self.name,
                action=action_name,
                idempotency_key=key,
                status=str(result.get("status") or "ok"),
                detail=str(result.get("detail") or ""),
                data=dict(result.get("data") or result),
            )
        return ExecutionResult(
            ok=True,
            adapter=self.name,
            action=action_name,
            idempotency_key=key,
            status="ok",
            data={"result": result},
        )
