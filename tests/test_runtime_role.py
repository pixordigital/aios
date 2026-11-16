"""Runtime role split — API must not own pollers or cron in split mode."""

import pytest

from aios.config import channels_are_remote, runs_channels, runs_cron, runtime_role


@pytest.mark.parametrize(
    "role,channels,cron,remote",
    [
        ("all", True, True, False),
        ("gateway", True, True, False),
        ("api", False, False, True),
        ("worker", False, False, False),
    ],
)
def test_role_matrix(monkeypatch, role, channels, cron, remote):
    from aios.config import settings

    monkeypatch.setattr(settings, "runtime_role", role)
    assert runtime_role() == role
    assert runs_channels() is channels
    assert runs_cron() is cron
    assert channels_are_remote() is remote


def test_role_is_case_and_space_insensitive(monkeypatch):
    from aios.config import settings

    monkeypatch.setattr(settings, "runtime_role", "  API ")
    assert runtime_role() == "api"
    assert channels_are_remote() is True


@pytest.mark.asyncio
async def test_api_role_enqueues_channel_sync(monkeypatch):
    from aios.config import settings
    from aios.api import channels as channels_api

    monkeypatch.setattr(settings, "runtime_role", "api")
    calls = []

    async def fake_enqueue(name, *args, **kwargs):
        calls.append((name, args, kwargs))

    monkeypatch.setattr("aios.tasks.queue.enqueue_job", fake_enqueue)

    class Row:
        id = "chan-1"
        agent_id = None
        team_id = None

    ok = await channels_api._sync_channel(Row(), True, None)

    assert ok is True
    assert calls == [
        ("aios.tasks.jobs.channel_sync_job", ("chan-1", True), {"priority": "high"})
    ]


@pytest.mark.asyncio
async def test_all_role_uses_local_manager(monkeypatch):
    from aios.config import settings
    from aios.api import channels as channels_api
    from aios.channels.manager import manager

    monkeypatch.setattr(settings, "runtime_role", "all")
    calls = []

    async def fake_sync(conn, is_active, agent_or_team=None, db=None):
        calls.append((conn.id, is_active))
        return is_active

    monkeypatch.setattr(manager, "sync", fake_sync)

    class Row:
        id = "chan-2"
        agent_id = None
        team_id = None

    ok = await channels_api._sync_channel(Row(), True, None)

    assert ok is True
    assert calls == [("chan-2", True)]
