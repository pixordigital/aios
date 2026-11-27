"""BusinessOS MCP jsonl runner."""
import json
import subprocess

from aios.core import mcp_business_os
from aios.core.mcp_business_os import BusinessOSMCPRunner

ROOT = "aios/templates/business_os"


def test_mcp_json_files_parse_as_jsonl():
    runner = BusinessOSMCPRunner(root=ROOT)
    entries = runner._entries()
    assert entries
    for e in entries:
        assert isinstance(e, dict) and e.get("command")


def test_run_tmp_mcp(tmp_path, monkeypatch):
    d = tmp_path / "Money"
    d.mkdir()
    (d / "mcp.json").write_text(
        json.dumps({"command": "money-update", "schedule": "hourly"}) + "\n"
    )
    runner = BusinessOSMCPRunner(root=str(tmp_path))
    entries = runner._entries()
    assert entries and entries[0]["command"] == "money-update"
    monkeypatch.setattr(
        mcp_business_os.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", ""),
    )
    out = runner.run("money-update")
    assert out["ok"] is True


def test_direct_send_denied_without_approval(tmp_path, monkeypatch):
    d = tmp_path / "Inbox_Support"
    d.mkdir()
    (d / "mcp.json").write_text(
        json.dumps({"command": "direct_send", "channel": "wa", "msg": "hi"}) + "\n"
    )
    calls = []

    def _run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(mcp_business_os.subprocess, "run", _run)
    runner = BusinessOSMCPRunner(root=str(tmp_path))
    out = runner.run("direct_send")
    assert out["ok"] is False
    assert out.get("denied") is True
    assert "approval" in out["error"].lower()
    assert calls == []


def test_unknown_command_denied(tmp_path, monkeypatch):
    d = tmp_path / "X"
    d.mkdir()
    (d / "mcp.json").write_text(json.dumps({"command": "rm-rf"}) + "\n")
    calls = []
    monkeypatch.setattr(
        mcp_business_os.subprocess,
        "run",
        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""),
    )
    runner = BusinessOSMCPRunner(root=str(tmp_path))
    out = runner.run("rm-rf")
    assert out["ok"] is False
    assert out.get("denied") is True
    assert calls == []
