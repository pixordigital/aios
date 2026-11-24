"""ICM-X binding of standalone agent runs: context, tools, timeout."""
from pathlib import Path

from aios.config import settings
from aios.core.agent import AgentRuntime
from aios.db.models import Agent
from aios.icm.contracts import load_stage_manifest, manifest_fingerprint
from aios.icm.team_workspaces import (
    AGENT_STAGES,
    TEAM_WORKSPACES,
    seed_team_workspaces,
)


def _agent(**overrides) -> Agent:
    data = {
        "id": "agent-1",
        "name": "sales-sdr",
        "org_id": "org-1",
        "llm_config": {"model": "openai/gpt-4o"},
        "tools": [
            "lead_score", "web_search", "crm_update_deal", "crm_merge_deals",
            "send_email", "current_datetime",
        ],
        "governance_config": {},
        "extra_data": {},
    }
    data.update(overrides)
    return Agent(**data)


def test_team_workspaces_seed_valid_manifests(tmp_path: Path):
    written = seed_team_workspaces(tmp_path, "org-1")
    assert len(written) == len(TEAM_WORKSPACES)
    for workspace in written:
        manifests = list(workspace.glob("L2/stages/*/stage.yaml"))
        assert manifests, workspace
        for path in manifests:
            manifest = load_stage_manifest(path)
            assert manifest.allowed_tools
            assert not set(manifest.allowed_tools) & set(manifest.denied_tools)


def test_every_agent_binding_points_at_a_seeded_stage(tmp_path: Path):
    seed_team_workspaces(tmp_path, "org-1")
    for agent_name, (workspace_id, stage_id) in AGENT_STAGES.items():
        stage_dir = (
            tmp_path / "tenants" / "org-1" / "workspaces" / workspace_id
            / "L2" / "stages" / stage_id
        )
        assert (stage_dir / "stage.yaml").is_file(), f"{agent_name}: {workspace_id}/{stage_id}"


def test_agent_runtime_applies_stage_context_tools_and_timeout(tmp_path: Path, monkeypatch):
    seed_team_workspaces(tmp_path, "org-1", workspaces=["sales_ops"])
    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    agent = _agent(extra_data={"icm": {"workspace_id": "sales_ops", "stage_id": "sdr_prospecting"}})

    runtime = AgentRuntime(agent)

    assert runtime.stage is not None
    assert "SDR Prospecting" in runtime.stage.loaded_context
    assert runtime._stage_timeout == 180
    assert "crm_merge_deals" in runtime._denied_tools
    # "__all__" means the manifest allowlist is now the whole policy.
    assert runtime._allowed_tools <= set(runtime.stage.manifest.allowed_tools)
    assert "crm_merge_deals" not in runtime._allowed_tools
    assert runtime._icm_budget.max_llm_calls == runtime.stage.manifest.max_llm_calls
    assert runtime._icm_budget.max_tool_calls == runtime.MAX_TOOL_CALLS


def test_agent_allowlist_is_intersected_with_stage(tmp_path: Path, monkeypatch):
    seed_team_workspaces(tmp_path, "org-1", workspaces=["sales_ops"])
    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    agent = _agent(
        governance_config={"allowed_tools": ["lead_score", "crm_merge_deals"]},
        extra_data={"icm": {"workspace_id": "sales_ops", "stage_id": "sdr_prospecting"}},
    )

    runtime = AgentRuntime(agent)

    assert runtime._allowed_tools == {"lead_score"}


def test_agent_without_icm_config_has_no_stage():
    runtime = AgentRuntime(_agent())
    assert runtime.stage is None
    assert runtime._allowed_tools == "__all__"
    assert runtime._icm_budget.max_llm_calls == runtime.MAX_ITERATIONS


def _approval_manifest():
    from aios.icm.contracts import StageManifest

    return StageManifest.model_validate({
        "id": "approval_stage",
        "version": "1.0.0",
        "mode": "deterministic",
        "approval_required": True,
        "allowed_tools": ["lead_score"],
    })


def test_agent_binding_injects_explicit_icm_preapproved(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    manifest = _approval_manifest()
    agent = _agent(extra_data={
        "icm": {
            "workspace_id": "sales_ops",
            "stage_manifest": manifest.model_dump(mode="json"),
            "preapproved": {
                "approved": True,
                "approval_id": "approval-explicit",
                "approved_fingerprint": manifest_fingerprint(manifest),
                "actions": ["approval_stage"],
            },
        }
    })

    runtime = AgentRuntime(agent)

    assert runtime.stage is not None
    assert runtime.stage.approval_bound is not None
    assert runtime.stage.approval_bound["source"] == "icm_preapproved"
    # execution gate should pass for allowed tool
    runtime._icm_enforce_tool("lead_score", conversation_id="conv-1")


def test_agent_tool_side_effect_key_reused_within_run(tmp_path: Path, monkeypatch):
    from aios.icm import enforcement
    from aios.icm.contracts import manifest_fingerprint

    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    manifest = _approval_manifest().model_copy(update={"side_effects": True})
    agent = _agent(extra_data={
        "icm": {
            "workspace_id": "sales_ops",
            "stage_manifest": manifest.model_dump(mode="json"),
            "preapproved": {
                "approved": True,
                "approval_id": "approval-dedupe",
                "approved_fingerprint": manifest_fingerprint(manifest),
                "actions": ["approval_stage"],
            },
        }
    })
    runtime = AgentRuntime(agent)

    original = enforcement.side_effect_already_applied
    checks = []

    def spy(applied, key):
        checks.append((set(applied), key))
        return original(applied, key)

    monkeypatch.setattr(enforcement, "side_effect_already_applied", spy)
    runtime._icm_enforce_tool("lead_score", conversation_id="conv-dedupe")
    runtime._icm_enforce_tool("lead_score", conversation_id="conv-dedupe")

    assert len(checks) == 2
    assert checks[0][1] == checks[1][1]
    assert checks[0][0] == set()
    assert checks[1][0] == {checks[1][1]}


def test_agent_binding_fails_closed_without_explicit_preapproved(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    agent = _agent(extra_data={
        "icm": {
            "workspace_id": "sales_ops",
            "stage_manifest": _approval_manifest().model_dump(mode="json"),
        }
    })

    try:
        AgentRuntime(agent)
        assert False, "expected PermissionError"
    except PermissionError as e:
        assert "requires approval" in str(e)


def test_agent_binding_rejects_nonexplicit_governance_markers(tmp_path: Path, monkeypatch):
    # Governance preapproved actions are not ICM founder approval; must not fabricate.
    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    agent = _agent(
        governance_config={"preapproved_actions": ["lead_score"]},
        extra_data={
            "icm": {
                "workspace_id": "sales_ops",
                "stage_manifest": _approval_manifest().model_dump(mode="json"),
            }
        },
    )

    try:
        AgentRuntime(agent)
        assert False, "expected PermissionError"
    except PermissionError:
        pass
