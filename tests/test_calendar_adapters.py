"""Calendar execution adapter skeletons: fail-closed, HITL for booking changes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from aios.core.adapters.calendar_calcom import CalComAdapter
from aios.core.adapters.calendar_google import GoogleCalendarAdapter


@dataclass
class FakeCalendarClient:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def _record(self, action: str, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        self.calls.append(
            {"action": action, "payload": dict(payload), "idempotency_key": idempotency_key}
        )
        return {"ok": True, "status": "ok", "data": {"action": action}}

    def availability(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        return self._record("availability", payload, idempotency_key)

    def create(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        return self._record("create", payload, idempotency_key)

    def reschedule(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        return self._record("reschedule", payload, idempotency_key)

    def cancel(self, *, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        return self._record("cancel", payload, idempotency_key)


def _google(*, configured: bool, client: Any = None, approved: bool = True) -> GoogleCalendarAdapter:
    kwargs: dict[str, Any] = {"client": client, "approved": approved}
    if configured:
        kwargs.update(credentials={"type": "service_account"}, calendar_id="primary")
    return GoogleCalendarAdapter(**kwargs)


def _calcom(*, configured: bool, client: Any = None, approved: bool = True) -> CalComAdapter:
    kwargs: dict[str, Any] = {"client": client, "approved": approved}
    if configured:
        kwargs.update(api_key="cal_test", event_type="intro", webhook_secret="whsec_test")
    return CalComAdapter(**kwargs)


ADAPTER_CASES = [
    pytest.param(_google, "google_calendar", id="google"),
    pytest.param(_calcom, "calcom", id="calcom"),
]


@pytest.mark.parametrize(("factory", "name"), ADAPTER_CASES)
def test_missing_config_fail_closed(factory, name):
    adapter = factory(configured=False, client=FakeCalendarClient())
    result = adapter.execute(
        action="availability",
        payload={"date": "2026-12-01"},
        idempotency_key="idem-missing-config",
    )
    assert result.ok is False
    assert result.adapter == name
    assert result.status == "denied"
    assert "not configured" in result.detail.lower()
    assert adapter.configured is False


@pytest.mark.parametrize(("factory", "name"), ADAPTER_CASES)
@pytest.mark.parametrize("action", ["create", "cancel"])
def test_booking_changes_require_approval(factory, name, action):
    client = FakeCalendarClient()
    adapter = factory(configured=True, client=client)
    result = adapter.execute(
        action=action,
        payload={"start": "2026-12-01T10:00:00Z"},
        idempotency_key=f"idem-{action}-no-approval",
    )
    assert result.ok is False
    assert result.adapter == name
    assert result.status == "denied"
    assert "approval" in result.detail.lower()
    assert client.calls == []


@pytest.mark.parametrize(("factory", "name"), ADAPTER_CASES)
def test_sandbox_injected_client_ok(factory, name):
    client = FakeCalendarClient()
    adapter = factory(configured=True, client=client)

    availability = adapter.execute(
        action="availability",
        payload={"date": "2026-12-01"},
        idempotency_key="idem-avail",
    )
    assert availability.ok is True
    assert availability.adapter == name
    assert availability.status == "ok"

    create = adapter.execute(
        action="create",
        payload={"start": "2026-12-01T10:00:00Z", "approved": True},
        idempotency_key="idem-create-approved",
    )
    assert create.ok is True
    assert create.adapter == name
    assert create.status == "ok"
    assert client.calls[0]["action"] == "availability"
    assert client.calls[1]["action"] == "create"
    assert client.calls[1]["idempotency_key"] == "idem-create-approved"
