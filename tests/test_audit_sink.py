"""Append-only audit sink: append, org scope, chain validation, rotation."""

import json

import pytest

from aios.core import audit_sink
from aios.governance.security import record_security_event


@pytest.fixture
def sink(tmp_path, monkeypatch):
    path = tmp_path / "audit" / "telemetry.jsonl"
    monkeypatch.setenv("AIOS_AUDIT_SINK_PATH", str(path))
    return path


def test_append_and_read_is_org_scoped_and_chained(sink):
    first = audit_sink.append("org-a", "telemetry.flush", {"messages": 1})
    second = audit_sink.append("org-b", "telemetry.flush", {"messages": 2})

    rows = audit_sink.read()
    assert [r["seq"] for r in rows] == [1, 2]
    assert rows[0]["prev_hash"] == audit_sink.GENESIS_HASH
    assert rows[1]["prev_hash"] == rows[0]["hash"]
    assert [r["org_id"] for r in audit_sink.read(org_id="org-a")] == ["org-a"]
    assert first["hash"] == rows[0]["hash"] and second["hash"] == rows[1]["hash"]


def test_tampered_record_fails_closed(sink):
    audit_sink.append("org-a", "telemetry.flush", {"messages": 1})
    audit_sink.append("org-a", "telemetry.flush", {"messages": 2})

    lines = sink.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["data"]["messages"] = 999  # keep hash, change content
    sink.write_text(
        "\n".join([json.dumps(record, sort_keys=True, separators=(",", ":"))] + lines[1:]) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(audit_sink.AuditChainError):
        audit_sink.read()


def test_mirror_telemetry_snapshot(sink):
    class FakeTelemetry:
        _metrics = {
            "agent-a:hour": {
                "agent_id": "agent-a",
                "org_id": "org-a",
                "hour": "2026-11-24-12",
                "messages": 3,
            }
        }

    assert audit_sink.mirror_telemetry(FakeTelemetry()) == 1
    rows = audit_sink.read(org_id="org-a")
    assert len(rows) == 1
    assert rows[0]["data"]["agent_id"] == "agent-a"
    assert "org_id" not in rows[0]["data"]


class _FlushingDB:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_record_security_event_mirrors_sanitized_fields(sink):
    db = _FlushingDB()
    evt = await record_security_event(
        db,
        org_id="org-a",
        source="api.test",
        event_type="security.auth.failure",
        severity="high",
        incident_id="inc-1",
        actor_type="human",
        actor_id="u-1",
        payload={"secret": "do-not-mirror"},
    )
    assert evt is not None
    rows = audit_sink.read(org_id="org-a")
    assert len(rows) == 1
    assert rows[0]["event"] == "security.auth.failure"
    assert rows[0]["data"] == {
        "event_type": "security.auth.failure",
        "severity": "high",
        "source": "api.test",
        "incident_id": "inc-1",
        "actor_type": "human",
        "actor_id": "u-1",
        "org_id": "org-a",
    }
    assert "do-not-mirror" not in sink.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_record_security_event_mirror_failure_never_raises(sink, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("sink down")

    monkeypatch.setattr(audit_sink, "append", boom)
    db = _FlushingDB()
    evt = await record_security_event(
        db, org_id="org-a", source="api.test", event_type="security.auth.failure"
    )
    assert evt is not None
    assert audit_sink.read() == []


def test_append_after_rotation_starts_new_chain(sink):
    audit_sink.append("org-a", "telemetry.flush", {"messages": 1})
    sink.unlink()

    rotated = audit_sink.append("org-a", "telemetry.flush", {"messages": 2})
    rows = audit_sink.read()
    assert rotated["seq"] == 1
    assert rotated["prev_hash"] == audit_sink.GENESIS_HASH
    assert len(rows) == 1 and rows[0]["hash"] == rotated["hash"]
