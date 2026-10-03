"""Cal.com booking tool — contract against the v2 OpenAPI shapes.

HTTP is faked at the AsyncClient boundary, so these pin request construction
(auth header, version header, payload shape) and response parsing without
needing a Cal.com instance.
"""

import pytest

from aios.config import settings
from aios.tools.cal_booking import CalBookingTool


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


_QUEUES: list = []
_CREATED: list = []


class _Client:
    """Records (method, path, params, json) and replays queued responses."""

    def __init__(self, *a, **k):
        self.headers = k.get("headers", {})
        self.calls = []
        self.queue = list(_QUEUES.pop(0)) if _QUEUES else []
        _CREATED.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, path, params=None):
        self.calls.append(("GET", path, params, None))
        return self.queue.pop(0)

    async def post(self, path, params=None, json=None):
        self.calls.append(("POST", path, params, json))
        return self.queue.pop(0)


@pytest.fixture
def _cfg(monkeypatch):
    yield _configure(monkeypatch)


def _configure(monkeypatch):
    monkeypatch.setattr(settings, "calcom_api_url", "http://cal:80")
    monkeypatch.setattr(settings, "calcom_api_key", "cal_test_123")
    monkeypatch.setattr(settings, "calcom_api_version", "2024-08-13")
    monkeypatch.setattr(settings, "calcom_event_type_id", 7)
    monkeypatch.setattr(settings, "calcom_timezone", "America/Sao_Paulo")
    monkeypatch.setattr("httpx.AsyncClient", _Client)
    _CREATED.clear()
    _QUEUES.clear()


def _tool():
    tool = CalBookingTool()
    tool._org_id, tool._agent_id = "o1", "a1"
    return tool


@pytest.mark.asyncio
async def test_fails_closed_without_key(monkeypatch, _cfg):
    monkeypatch.setattr(settings, "calcom_api_key", "")
    out = await _tool().run("availability", event_type_id=7, start="2026-10-10T00:00:00Z", end="2026-10-11T00:00:00Z")
    assert out["ok"] is False and "AIOS_CALCOM_API_KEY" in out["error"]


@pytest.mark.asyncio
async def test_availability_request_shape(_cfg):
    _QUEUES.append([_Resp(200, {"status": "success", "data": {"2026-10-10": [{"start": "2026-10-10T14:00:00Z"}]}})])
    out = await _tool().run("availability", start="2026-10-10T00:00:00Z", end="2026-10-11T00:00:00Z")
    assert out["ok"] is True
    assert out["slots"]["data"]["2026-10-10"][0]["start"].endswith("14:00:00Z")
    method, path, params, _ = _CREATED[0].calls[0]
    assert (method, path) == ("GET", "/v2/slots")
    assert params["eventTypeId"] == 7  # default from settings
    assert params["timeZone"] == "America/Sao_Paulo"
    assert params["cal-api-version"] == "2024-09-04"  # pinned per OpenAPI
    assert _CREATED[0].headers["Authorization"] == "Bearer cal_test_123"


@pytest.mark.asyncio
async def test_availability_needs_window(_cfg):
    out = await _tool().run("availability", start="2026-10-10T00:00:00Z")
    assert out["ok"] is False


@pytest.mark.asyncio
async def test_book_builds_spec_payload(_cfg):
    _QUEUES.append([_Resp(201, {"status": "success", "data": {
        "uid": "abc123", "status": "accepted", "meetingUrl": "https://meet/x"}})])
    out = await _tool().run(
        "book", event_type_id=7, start="2026-10-10T14:00:00Z",
        attendee_name="Lead", attendee_email="lead@x.com", notes="SDR Ana",
    )
    assert out == {"ok": True, "uid": "abc123", "meeting_url": "https://meet/x", "status": "accepted"}
    _, path, _, payload = _CREATED[0].calls[0]
    assert path == "/v2/bookings"
    assert payload["eventTypeId"] == 7
    assert payload["attendee"] == {"name": "Lead", "email": "lead@x.com", "timeZone": "America/Sao_Paulo"}
    assert payload["metadata"]["source"] == "aios-sdr"


@pytest.mark.asyncio
async def test_book_rejects_incomplete(_cfg):
    out = await _tool().run("book", start="2026-10-10T14:00:00Z")
    assert out["ok"] is False  # no attendee, no confirmation possible


@pytest.mark.asyncio
async def test_book_surfaces_provider_error(_cfg):
    _QUEUES.append([_Resp(400, {"error": {"message": "slot taken"}})])
    out = await _tool().run(
        "book", event_type_id=7, start="2026-10-10T14:00:00Z",
        attendee_name="Lead", attendee_email="lead@x.com",
    )
    assert out["ok"] is False and "400" in out["error"]


@pytest.mark.asyncio
async def test_cancel_posts_reason(_cfg):
    _QUEUES.append([_Resp(200, {"status": "success", "data": {}})])
    out = await _tool().run("cancel", booking_uid="abc123", cancellation_reason="lead pediu")
    assert out == {"ok": True, "cancelled": "abc123"}
    _, path, _, payload = _CREATED[0].calls[0]
    assert path == "/v2/bookings/abc123/cancel"
    assert payload == {"cancellationReason": "lead pediu"}


@pytest.mark.asyncio
async def test_event_types_mapped(_cfg):
    _QUEUES.append([_Resp(200, {"status": "success", "data": [
        {"id": 7, "slug": "visita-30", "title": "Visita 30min", "lengthInMinutes": 30}]})])
    out = await _tool().run("event_types")
    assert out == {"ok": True, "event_types": [
        {"id": 7, "slug": "visita-30", "title": "Visita 30min", "length_minutes": 30}]}


@pytest.mark.asyncio
async def test_unknown_action(_cfg):
    assert (await _tool().run("teleport"))["ok"] is False


def test_cal_booking_registered():
    from aios.tools.registry import TOOL_REGISTRY

    assert "cal_booking" in TOOL_REGISTRY
