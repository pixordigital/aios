"""ICM-X binding of standalone agent runs: context, tools, timeout."""
from pathlib import Path

from aios.config import settings
from aios.core.agent import AgentRuntime
from aios.db.models import Agent
from aios.icm.contracts import load_stage_manifest
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
