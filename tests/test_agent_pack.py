import json
from pathlib import Path

import pytest

from aios.core.agent_pack import (
    MAX_PACK_BYTES,
    AgentPackManifest,
    AgentPackValidationError,
    _checksum_fingerprint,
    load_agent_pack,
    manifest_fingerprint,
    validate_agent_pack,
)


def _valid_manifest(**overrides):
    data = {
        "schema_version": "1.0.0",
        "version": "1.0.0",
        "identity": {
            "id": "sales_sdr",
            "name": "Sales SDR",
            "agent_type": "sdr",
            "description": "desc",
            "owner": "team",
            "tags": ["sales"],
        },
        "prompt": {
            "system_prompt": "You are an SDR.",
            "variables": ["company"],
            "scaffold_required": True,
        },
        "tools": {
            "allowed_tools": ["crm_lookup"],
            "denied_tools": ["delete_db"],
            "risk_classes": {"crm_lookup": "read"},
        },
        "routines": [
            {
                "id": "qualify",
                "trigger": "new_lead",
                "workflow_id": "wf1",
                "stage_ref": "stages/qualify.v1",
                "enabled": True,
            }
        ],
        "approvals": {
            "mode": "ask_tools",
            "required_for": ["send_email"],
            "approval_ttl_seconds": 300,
            "explicit_preapproved_allowed": False,
        },
        "memory_scope": {
            "scopes": ["conversation", "agent"],
            "max_short_term_messages": 100,
            "long_term_enabled": True,
            "episodic_enabled": True,
            "redact_patterns": [],
        },
        "runtime_targets": [
            {"target": "local_proc", "entrypoint": "main:run", "image": None, "resources": {}}
        ],
        "changelog": [
            {"version": "1.0.0", "date": "2026-11-25", "summary": "init", "author": "pixor"}
        ],
        "provenance": {
            "source": "git:test",
            "created_by": "tester",
            "created_at": "2026-11-25T00:00:00Z",
            "checksum_sha256": None,
            "signature": None,
            "parent_fingerprint": None,
        },
    }
    data.update(overrides)
    return data


def test_valid_minimal_manifest_loads_and_fingerprint_stable(tmp_path: Path):
    p = tmp_path / "pack.json"
    p.write_text(json.dumps(_valid_manifest()), encoding="utf-8")
    m1 = load_agent_pack(p)
    m2 = load_agent_pack(p)
    assert isinstance(m1, AgentPackManifest)
    assert manifest_fingerprint(m1) == manifest_fingerprint(m2)
    assert m1.schema_version == "1.0.0"
    assert m1.runtime_targets[0].target == "local_proc"


def test_unknown_field_rejected_top_and_nested():
    bad_top = _valid_manifest()
    bad_top["unknown"] = "x"
    with pytest.raises(AgentPackValidationError):
        validate_agent_pack(bad_top)

    bad_nested = _valid_manifest()
    bad_nested["identity"] = {**bad_nested["identity"], "extra": "x"}
    with pytest.raises(AgentPackValidationError):
        validate_agent_pack(bad_nested)


def test_oversize_reject(tmp_path: Path):
    p = tmp_path / "big.json"
    payload = _valid_manifest()
    payload["prompt"]["system_prompt"] = "A" * (MAX_PACK_BYTES + 1)
    p.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AgentPackValidationError, match="exceeds"):
        load_agent_pack(p)


def test_bad_json_yaml_non_mapping(tmp_path: Path):
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not json", encoding="utf-8")
    with pytest.raises(AgentPackValidationError):
        load_agent_pack(bad_json)

    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(":\n  - [", encoding="utf-8")
    with pytest.raises(AgentPackValidationError):
        load_agent_pack(bad_yaml)

    non_map = tmp_path / "list.json"
    non_map.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(AgentPackValidationError, match="mapping/object"):
        load_agent_pack(non_map)


def test_bad_semver_empty_prompt_missing_runtime_targets():
    bad_semver = _valid_manifest(version="1.0")
    with pytest.raises(AgentPackValidationError):
        validate_agent_pack(bad_semver)

    empty_prompt = _valid_manifest()
    empty_prompt["prompt"] = {**empty_prompt["prompt"], "system_prompt": ""}
    with pytest.raises(AgentPackValidationError):
        validate_agent_pack(empty_prompt)

    missing_rt = _valid_manifest(runtime_targets=[])
    with pytest.raises(AgentPackValidationError):
        validate_agent_pack(missing_rt)


def test_tool_overlap_rejected():
    data = _valid_manifest()
    data["tools"] = {
        "allowed_tools": ["a", "b"],
        "denied_tools": ["b", "c"],
        "risk_classes": {},
    }
    with pytest.raises(AgentPackValidationError, match="overlap"):
        validate_agent_pack(data)


def test_duplicate_routine_ids_rejected():
    data = _valid_manifest()
    r = data["routines"][0]
    data["routines"] = [r, {**r, "trigger": "other"}]
    with pytest.raises(AgentPackValidationError, match="duplicate routine ids"):
        validate_agent_pack(data)


def test_bad_stage_ref_rejected():
    data = _valid_manifest()
    data["routines"][0]["stage_ref"] = "bad ref with space"
    with pytest.raises(AgentPackValidationError, match="stage_ref"):
        validate_agent_pack(data)


def test_changelog_version_mismatch_rejected():
    data = _valid_manifest(version="1.2.0")
    data["changelog"] = [{"version": "1.0.0", "date": "2026-11-25", "summary": "init", "author": ""}]
    with pytest.raises(AgentPackValidationError, match="changelog"):
        validate_agent_pack(data)


def test_memory_scopes_empty_rejected():
    data = _valid_manifest()
    data["memory_scope"] = {**data["memory_scope"], "scopes": []}
    with pytest.raises(AgentPackValidationError, match="scopes"):
        validate_agent_pack(data)


def test_checksum_mismatch_rejected_when_provided():
    data = _valid_manifest()
    data["provenance"]["checksum_sha256"] = "0" * 64
    with pytest.raises(AgentPackValidationError, match="checksum_sha256 mismatch"):
        validate_agent_pack(data)


def test_checksum_match_accepts():
    data = _valid_manifest()
    m = validate_agent_pack(data)
    data["provenance"]["checksum_sha256"] = _checksum_fingerprint(m)
    m2 = validate_agent_pack(data)
    assert m2.provenance.checksum_sha256 == _checksum_fingerprint(m2)


def test_mode_none_explicit_preapproved_rejected():
    data = _valid_manifest()
    data["approvals"] = {
        "mode": "none",
        "required_for": [],
        "approval_ttl_seconds": 300,
        "explicit_preapproved_allowed": True,
    }
    with pytest.raises(AgentPackValidationError, match="unsafe"):
        validate_agent_pack(data)


def test_roundtrip_load_dump_fingerprint_unchanged(tmp_path: Path):
    p = tmp_path / "pack.json"
    p.write_text(json.dumps(_valid_manifest()), encoding="utf-8")
    m = load_agent_pack(p)
    fp1 = manifest_fingerprint(m)
    dumped = json.dumps(m.model_dump(mode="json"))
    p2 = tmp_path / "pack2.json"
    p2.write_text(dumped, encoding="utf-8")
    m2 = load_agent_pack(p2)
    assert manifest_fingerprint(m2) == fp1
