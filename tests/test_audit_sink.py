"""Append-only audit sink: append, org scope, chain validation, rotation."""

import json

import pytest

from aios.core import audit_sink


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


def test_append_after_rotation_starts_new_chain(sink):
    audit_sink.append("org-a", "telemetry.flush", {"messages": 1})
    sink.unlink()

    rotated = audit_sink.append("org-a", "telemetry.flush", {"messages": 2})
    rows = audit_sink.read()
    assert rotated["seq"] == 1
    assert rotated["prev_hash"] == audit_sink.GENESIS_HASH
    assert len(rows) == 1 and rows[0]["hash"] == rotated["hash"]
