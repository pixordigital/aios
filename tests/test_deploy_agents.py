"""Offline tests for scripts/deploy_agents.py — provider and DB are mocked."""

import asyncio
import importlib
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
cli = importlib.import_module("deploy_agents")


def _agent(ident, name, status="draft", model="openai/gpt-4o-mini"):
    return SimpleNamespace(
        id=ident, name=name, status=status, org_id="org1",
        llm_config={"model": model}, system_prompt="probe",
        tools=[], governance_config={}, extra_data={},
    )


class FakeDB:
    def __init__(self, agents):
        self.by_id = {agent.id: agent for agent in agents}
        self.commits = 0

    async def get(self, _model, ident):
        return self.by_id.get(ident)

    async def commit(self):
        self.commits += 1


def _session(db):
    @asynccontextmanager
    async def factory():
        yield db
    return factory


def _healthy(_model):
    return {"provider": "OpenRouterProvider", "model": _model,
            "available": True, "credentials_configured": True, "circuit": "closed"}


def _patch_common(monkeypatch, agents, db):
    async def load(_org_id):
        return agents

    monkeypatch.setattr(cli, "_load_agents", load)
    monkeypatch.setattr(cli, "db_session", _session(db))
    monkeypatch.setattr(cli, "provider_health", _healthy)
    monkeypatch.setattr(cli.getpass, "getuser", lambda: "tester")


@pytest.mark.asyncio
async def test_dry_run_is_default_and_writes_only_snapshot(tmp_path, capsys, monkeypatch):
    agents = [_agent("a1", "draft-one"), _agent("a2", "live-one", "active"),
              _agent("old", "legacy", "archived")]
    db = FakeDB(agents)
    _patch_common(monkeypatch, agents, db)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("dry run must not probe")

    monkeypatch.setattr(cli, "probe_agent", forbidden)
    monkeypatch.setattr(cli, "deploy_and_verify", forbidden)
    backup = tmp_path / "snapshot.json"

    code = await cli.main(["--org-id", "org1", "--backup", str(backup)])
    report = json.loads(capsys.readouterr().out)

    assert code == cli.EXIT_OK
    assert report["mode"] == "dry-run"
    assert report["would_deploy"] == ["a1", "a2"]
    assert report["skipped_archived"] == []
    snapshot = json.loads(backup.read_text(encoding="utf-8"))
    assert [row["status"] for row in snapshot["agents"]] == ["draft", "active", "archived"]
    assert db.commits == 0


@pytest.mark.asyncio
async def test_named_archived_agent_skipped_and_unknown_refused(tmp_path, capsys, monkeypatch):
    agents = [_agent("a1", "draft-one"), _agent("old", "legacy", "archived")]
    db = FakeDB(agents)
    _patch_common(monkeypatch, agents, db)

    async def noop(*_args, **_kwargs):
        raise AssertionError("dry run must not probe")

    monkeypatch.setattr(cli, "probe_agent", noop)
    monkeypatch.setattr(cli, "deploy_and_verify", noop)
    backup = tmp_path / "named.json"

    code = await cli.main(["--org-id", "org1", "--backup", str(backup),
                           "--agent", "a1", "--agent", "legacy"])
    report = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_OK
    assert report["would_deploy"] == ["a1"]
    assert report["skipped_archived"] == ["legacy"]

    missing_backup = tmp_path / "missing.json"
    code = await cli.main(["--org-id", "org1", "--backup", str(missing_backup),
                           "--agent", "nope"])
    assert code == cli.EXIT_PREFLIGHT
    assert not missing_backup.exists()


@pytest.mark.asyncio
async def test_missing_credentials_refuse_before_backup(tmp_path, monkeypatch):
    agents = [_agent("a1", "draft-one")]
    db = FakeDB(agents)
    _patch_common(monkeypatch, agents, db)
    monkeypatch.setattr(cli, "provider_health", lambda _model: {
        "provider": "OpenRouterProvider", "model": _model,
        "available": False, "credentials_configured": False, "circuit": "closed",
    })

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("preflight refusal must not deploy")

    monkeypatch.setattr(cli, "probe_agent", forbidden)
    monkeypatch.setattr(cli, "deploy_and_verify", forbidden)
    backup = tmp_path / "never.json"

    code = await cli.main(["--org-id", "org1", "--backup", str(backup), "--apply"])

    assert code == cli.EXIT_PREFLIGHT
    assert not backup.exists()
    assert db.commits == 0


@pytest.mark.asyncio
async def test_apply_isolates_failed_probe_and_bounds_concurrency(tmp_path, capsys, monkeypatch):
    agents = [_agent("a1", "one"), _agent("a2", "two"),
              _agent("bad", "broken"), _agent("live", "already", "active")]
    db = FakeDB(agents)
    _patch_common(monkeypatch, agents, db)
    entered = peak = 0

    async def probe(agent, timeout=None):
        nonlocal entered, peak
        entered += 1
        peak = max(peak, entered)
        await asyncio.sleep(0)
        entered -= 1
        if agent.id == "bad":
            raise RuntimeError("provider call failed: invalid key")
        return {"model": "openai/gpt-4o-mini", "latency_ms": 4}

    deployed = []

    async def deploy(session, agent, org_id, user_id=None):
        deployed.append(agent.id)
        assert org_id == "org1"
        assert user_id == "tester"
        await session.commit()
        agent.status = "active"
        return {"agent": agent, "evidence": {"latency_ms": 4}}

    monkeypatch.setattr(cli, "probe_agent", probe)
    monkeypatch.setattr(cli, "deploy_and_verify", deploy)
    backup = tmp_path / "apply.json"

    code = await cli.main(["--org-id", "org1", "--backup", str(backup),
                           "--apply", "--concurrency", "2"])
    report = json.loads(capsys.readouterr().out)

    assert code == cli.EXIT_PARTIAL
    assert peak <= 2
    assert "bad" not in deployed
    assert set(deployed) == {"a1", "a2", "live"}
    assert db.commits == 3
    assert report["failed"] == ["bad"]
    assert backup.exists()


@pytest.mark.asyncio
async def test_all_failed_probes_write_no_agent_rows(tmp_path, capsys, monkeypatch):
    agents = [_agent("a1", "one"), _agent("a2", "two")]
    db = FakeDB(agents)
    _patch_common(monkeypatch, agents, db)

    async def probe(_agent, timeout=None):
        raise RuntimeError("tools unavailable: missing_tool")

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("failed probe must not reach deploy_and_verify")

    monkeypatch.setattr(cli, "probe_agent", probe)
    monkeypatch.setattr(cli, "deploy_and_verify", forbidden)
    backup = tmp_path / "failed-probes.json"

    code = await cli.main(["--org-id", "org1", "--backup", str(backup), "--apply"])
    report = json.loads(capsys.readouterr().out)

    assert code == cli.EXIT_PARTIAL
    assert db.commits == 0
    assert report["deployed"] == []
    assert report["failed"] == ["a1", "a2"]
