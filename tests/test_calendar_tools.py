"""Calendar tools: honest failure without credentials, real behavior with them.

The old calendar_create_event returned ok:true with a fake calendar.mock link
when unconfigured — agents told users meetings were booked and nothing
happened. These tests pin the fail-closed behavior and the real paths
(with a stubbed google client, since CI has no Google account).
"""

import json
import sys
import types

import pytest


def _install_google_stub(monkeypatch, events_impl=None, freebusy_impl=None):
    """Stub google.oauth2.service_account + googleapiclient.discovery."""
    oauth2 = types.ModuleType("google.oauth2")
    sa_mod = types.ModuleType("google.oauth2.service_account")

    class FakeCreds:
        @classmethod
        def from_service_account_info(cls, info, scopes=None):
            assert info["client_email"]
            return cls()

    sa_mod.Credentials = FakeCreds
    oauth2.service_account = sa_mod

    gapi = types.ModuleType("googleapiclient")
    disc = types.ModuleType("googleapiclient.discovery")

    class FakeEvents:
        def __init__(self, impl):
            self.impl = impl
            self.kwargs = None

        def insert(self, **kw):
            self.kwargs = kw
            parent = self

            class R:
                def execute(self):
                    return parent.impl("insert", kw)

            return R()

        def list(self, **kw):
            self.kwargs = kw
            parent = self

            class R:
                def execute(self):
                    return parent.impl("list", kw)

            return R()

    class FakeFreebusy:
        def __init__(self, impl):
            self.impl = impl

        def query(self, **kw):
            parent = self

            class R:
                def execute(self):
                    return parent.impl("query", kw)

            return R()

    class FakeSvc:
        def events(self):
            return FakeEvents(events_impl or (lambda op, kw: {}))

        def freebusy(self):
            return FakeFreebusy(freebusy_impl or (lambda op, kw: {}))

    disc.build = lambda *a, **k: FakeSvc()
    gapi.discovery = disc

    google = types.ModuleType("google")
    google.oauth2 = oauth2
    google.__path__ = []
    sys.modules["google"] = google
    sys.modules["google.oauth2"] = oauth2
    sys.modules["google.oauth2.service_account"] = sa_mod
    sys.modules["googleapiclient"] = gapi
    sys.modules["googleapiclient.discovery"] = disc
    monkeypatch.setattr("sys.modules", sys.modules)


CREDS = json.dumps({"client_email": "bot@proj.iam.gserviceaccount.com", "token_uri": "x"})


@pytest.fixture
def creds_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CALENDAR_CREDENTIALS", CREDS)
    monkeypatch.delenv("AIOS_GOOGLE_CALENDAR_CREDENTIALS", raising=False)


class TestUnconfigured:
    """Without credentials: explicit failure, never a fake success."""

    @pytest.mark.asyncio
    async def test_create_fails_closed(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_CALENDAR_CREDENTIALS", raising=False)
        monkeypatch.delenv("AIOS_GOOGLE_CALENDAR_CREDENTIALS", raising=False)
        from aios.tools.calendar import CalendarTool

        res = await CalendarTool().run(title="X", datetime_iso="2026-10-01T10:00:00-03:00")
        assert res["ok"] is False
        assert "não configurado" in res["error"]

    @pytest.mark.asyncio
    async def test_availability_fails_closed(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_CALENDAR_CREDENTIALS", raising=False)
        monkeypatch.delenv("AIOS_GOOGLE_CALENDAR_CREDENTIALS", raising=False)
        from aios.tools.calendar import CalendarAvailabilityTool

        res = await CalendarAvailabilityTool().run(date="2026-10-01")
        assert res["ok"] is False

    @pytest.mark.asyncio
    async def test_list_fails_closed(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_CALENDAR_CREDENTIALS", raising=False)
        monkeypatch.delenv("AIOS_GOOGLE_CALENDAR_CREDENTIALS", raising=False)
        from aios.tools.calendar import CalendarListTool

        res = await CalendarListTool().run()
        assert res["ok"] is False

    def test_no_mock_link_anywhere(self):
        from pathlib import Path

        src = Path("aios/tools/calendar.py").read_text()
        # skip the module docstring (documents the removed mock)
        _, _, code = src.partition('"""')
        _, _, code = code.partition('"""')
        assert "calendar.mock" not in code
        assert '"mock"' not in code and "'mock'" not in code


class TestConfigured:
    @pytest.mark.asyncio
    async def test_create_returns_real_link(self, monkeypatch, creds_env):
        _install_google_stub(
            monkeypatch,
            events_impl=lambda op, kw: {"id": "ev1", "htmlLink": "https://cal/ev1"},
        )
        from aios.tools.calendar import CalendarTool

        res = await CalendarTool().run(
            title="Reunião",
            datetime_iso="2026-10-01T10:00:00-03:00",
            attendee_email="lead@x.com",
            duration_min=45,
        )
        assert res["ok"] is True
        assert res["provider"] == "google_calendar"
        assert res["event_link"] == "https://cal/ev1"
        assert res["end"].startswith("2026-10-01T10:45")

    @pytest.mark.asyncio
    async def test_availability_computes_free_gaps(self, monkeypatch, creds_env):
        _install_google_stub(
            monkeypatch,
            freebusy_impl=lambda op, kw: {
                "calendars": {
                    "primary": {
                        "busy": [{"start": "2026-10-01T10:00:00-03:00", "end": "2026-10-01T11:00:00-03:00"}]
                    }
                }
            },
        )
        from aios.tools.calendar import CalendarAvailabilityTool

        res = await CalendarAvailabilityTool().run(date="2026-10-01")
        assert res["ok"] is True
        assert len(res["busy"]) == 1
        # free before 10h and after 11h inside 08-18
        assert len(res["free"]) == 2
        assert res["free"][0]["end"].startswith("2026-10-01T10:00")
        assert res["free"][1]["start"].startswith("2026-10-01T11:00")

    @pytest.mark.asyncio
    async def test_list_returns_events(self, monkeypatch, creds_env):
        _install_google_stub(
            monkeypatch,
            events_impl=lambda op, kw: {
                "items": [
                    {
                        "id": "a",
                        "summary": "Call",
                        "start": {"dateTime": "2026-10-02T09:00:00-03:00"},
                        "end": {"dateTime": "2026-10-02T09:30:00-03:00"},
                        "htmlLink": "https://cal/a",
                        "attendees": [{"email": "c@x.com"}],
                    }
                ]
            },
        )
        from aios.tools.calendar import CalendarListTool

        res = await CalendarListTool().run(time_min="2026-10-01T00:00:00-03:00")
        assert res["ok"] is True
        assert res["count"] == 1
        assert res["events"][0]["attendees"] == ["c@x.com"]

    @pytest.mark.asyncio
    async def test_bad_datetime_rejected(self, monkeypatch, creds_env):
        _install_google_stub(monkeypatch)
        from aios.tools.calendar import CalendarTool

        res = await CalendarTool().run(title="X", datetime_iso="not-a-date")
        assert res["ok"] is False
