import asyncio
from types import SimpleNamespace

import pytest


class _DummyDB:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def execute(self, *args, **kwargs):
        return SimpleNamespace()


class _DummySessionCtx:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_backup_tick_rejects_unexpected_script_path(monkeypatch, tmp_path):
    import aios.core.cron_scheduler as cron

    events = []
    monkeypatch.setattr(cron, "_last_backup_day", None)
    monkeypatch.setenv("AIOS_BACKUP_ENABLED", "1")
    monkeypatch.setattr("aios.core.audit_sink.append", lambda *a, **k: events.append((a, k)) or {})

    fake_now = SimpleNamespace(hour=3, minute=0, date=lambda: SimpleNamespace(isoformat=lambda: "2026-11-27"))
    monkeypatch.setattr(cron, "datetime", SimpleNamespace(now=lambda tz=None: fake_now, timezone=cron.timezone))

    real_resolve = cron.pathlib.Path.resolve
    real_exists = cron.pathlib.Path.exists
    repo_root = cron.pathlib.Path(cron.__file__).resolve().parents[2]
    allowed_real = {
        str((repo_root / "deploy" / "backup.sh").resolve()),
        str(cron.pathlib.Path("/app/deploy/backup.sh").resolve()),
    }
    counter = {"n": 0}

    def fake_resolve(self, strict=False):
        real = real_resolve(self)
        if str(real) in allowed_real or self.name == "backup.sh":
            counter["n"] += 1
            p = tmp_path / f"bad{counter['n']}" / "backup.sh"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("#!/bin/sh\necho bad\n", encoding="utf-8")
            return p
        return real

    def fake_exists(self):
        try:
            real = str(real_resolve(self))
        except Exception:
            real = str(self)
        if real in allowed_real or self.name == "backup.sh":
            return True
        return real_exists(self)

    monkeypatch.setattr(cron.pathlib.Path, "resolve", fake_resolve)
    monkeypatch.setattr(cron.pathlib.Path, "exists", fake_exists)

    called = {"run": False}

    def _boom(*args, **kwargs):
        called["run"] = True
        raise AssertionError("subprocess should not run")

    monkeypatch.setattr(cron.subprocess, "run", _boom)

    await cron._backup_tick()

    assert called["run"] is False
    assert any(a[1] == "cron.backup.rejected" for a, _ in events)


@pytest.mark.asyncio
async def test_dev_subprocess_disabled_by_default(monkeypatch):
    from aios.core import dev_cli

    events = []
    monkeypatch.delenv("AIOS_DEV_SUBPROCESS_ENABLED", raising=False)
    monkeypatch.setattr(dev_cli, "_dev_subprocess_enabled", lambda: False)
    monkeypatch.setattr("aios.core.audit_sink.append", lambda *a, **k: events.append((a, k)) or {})

    called = {"proc": False}

    async def _boom(*args, **kwargs):
        called["proc"] = True
        raise AssertionError("subprocess should not start")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _boom)

    res = await dev_cli.run_claude("hello")

    assert called["proc"] is False
    assert res["ok"] is False
    assert "disabled" in res["error"].lower()
    assert any(a[1] == "dev.subprocess.blocked" for a, _ in events)


@pytest.mark.asyncio
async def test_subagent_spawn_denied_when_disabled(monkeypatch):
    from aios.core.subagent import SubAgentPool, SubagentSpawnError

    events = []
    monkeypatch.setenv("AIOS_SUBAGENT_SPAWN_ENABLED", "0")
    monkeypatch.setattr("aios.core.audit_sink.append", lambda *a, **k: events.append((a, k)) or {})

    pool = SubAgentPool(max_concurrent=1)
    with pytest.raises(SubagentSpawnError):
        await pool.spawn({"id": "a1", "org_id": "org1"}, "do work", timeout=1)

    assert any(a[1] == "subagent.spawn.blocked" for a, _ in events)


@pytest.mark.asyncio
async def test_subagent_spawn_denied_on_quota_failure(monkeypatch):
    from aios.core.subagent import SubAgentPool, SubagentSpawnError

    events = []
    monkeypatch.setenv("AIOS_SUBAGENT_SPAWN_ENABLED", "1")
    monkeypatch.setattr("aios.core.audit_sink.append", lambda *a, **k: events.append((a, k)) or {})

    async def _deny(org_id, db):
        return False, "quota exceeded"

    monkeypatch.setattr("aios.core.limits.check_org_limits", _deny)
    monkeypatch.setattr("aios.db.backend.db_session", lambda: _DummySessionCtx(_DummyDB()))

    pool = SubAgentPool(max_concurrent=1)
    with pytest.raises(SubagentSpawnError, match="quota exceeded"):
        await pool.spawn({"id": "a1", "org_id": "org1"}, "do work", timeout=1)

    assert any(a[1] == "subagent.spawn.requested" for a, _ in events) is False
