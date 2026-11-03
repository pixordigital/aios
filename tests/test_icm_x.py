from pathlib import Path

import pytest
from pydantic import ValidationError

from aios.icm.contracts import StageManifest, load_stage_manifest, manifest_fingerprint
from aios.icm.workspace import WorkspacePaths, load_context_files


def _manifest(**overrides):
    data = {
        "id": "company_research",
        "version": "1.0.0",
        "mode": "llm",
        "max_llm_calls": 2,
        "max_cost_usd": 0.03,
        "allowed_tools": ["company_lookup"],
        "context": {"layers": ["identity", "stage", "static_references"]},
    }
    data.update(overrides)
    return data


def test_stage_manifest_validates_and_fingerprints_stably():
    first = StageManifest.model_validate(_manifest())
    second = StageManifest.model_validate(_manifest())
    assert manifest_fingerprint(first) == manifest_fingerprint(second)


def test_stage_manifest_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        StageManifest.model_validate(_manifest(unrestricted=True))


def test_deterministic_stage_cannot_spend_llm_budget():
    with pytest.raises(ValidationError):
        StageManifest.model_validate({
            "id": "normalize_lead",
            "version": "1.0.0",
            "mode": "deterministic",
            "max_llm_calls": 1,
        })


def test_llm_stage_requires_a_positive_cost_budget():
    with pytest.raises(ValidationError):
        StageManifest.model_validate(_manifest(max_cost_usd=0))


def test_tool_allow_deny_overlap_is_rejected():
    with pytest.raises(ValidationError):
        StageManifest.model_validate(_manifest(denied_tools=["company_lookup"]))


def test_yaml_manifest_loads(tmp_path: Path):
    manifest = tmp_path / "stage.yaml"
    manifest.write_text(
        """id: company_research
version: 1.0.0
mode: llm
max_llm_calls: 1
max_cost_usd: 0.05
""",
        encoding="utf-8",
    )
    assert load_stage_manifest(manifest).id == "company_research"


def test_workspace_paths_are_tenant_scoped_and_reject_traversal(tmp_path: Path):
    paths = WorkspacePaths(tmp_path)
    run = paths.ensure_run_directories("org_1", "sales", "run_1")
    assert run.is_relative_to(tmp_path.resolve())
    assert (run / "artifacts").is_dir()
    with pytest.raises(ValueError):
        paths.workspace("../other-tenant", "sales")


def test_context_loader_filters_layers_and_fingerprints(tmp_path: Path):
    (tmp_path / "identity.md").write_text("Workspace identity", encoding="utf-8")
    (tmp_path / "private.md").write_text("Do not load", encoding="utf-8")
    text, hashes = load_context_files(
        tmp_path,
        {"identity": ["identity.md"], "run_artifacts": ["private.md"]},
        allowed_layers=["identity"],
    )
    assert "Workspace identity" in text
    assert "Do not load" not in text
    assert "identity.md" in hashes


def test_context_loader_rejects_path_traversal(tmp_path: Path):
    with pytest.raises(ValueError):
        load_context_files(tmp_path, {"stage": ["../secret.md"]})


def test_context_loader_enforces_size_limit(tmp_path: Path):
    (tmp_path / "large.md").write_text("x" * 20, encoding="utf-8")
    with pytest.raises(ValueError):
        load_context_files(tmp_path, {"stage": ["large.md"]}, max_file_bytes=10)


def test_context_loader_empty_allowlist_loads_nothing(tmp_path: Path):
    (tmp_path / "identity.md").write_text("Must not load", encoding="utf-8")
    text, hashes = load_context_files(
        tmp_path, {"identity": ["identity.md"]}, allowed_layers=[]
    )
    assert text == ""
    assert hashes == {}


def test_workspace_rejects_symlink_escape_before_writing(tmp_path: Path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir()
    (root / "tenants").symlink_to(outside, target_is_directory=True)
    paths = WorkspacePaths(root)
    with pytest.raises(ValueError):
        paths.ensure_run_directories("org_1", "sales", "run_1")
    assert list(outside.iterdir()) == []


def test_workspace_paths_reject_symlink_escape_before_creating_run(tmp_path: Path):
    paths = WorkspacePaths(tmp_path / "storage")
    outside = tmp_path / "outside"
    outside.mkdir()
    tenants = tmp_path / "storage" / "tenants"
    tenants.mkdir(parents=True)
    (tenants / "org_1").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError):
        paths.ensure_run_directories("org_1", "sales", "run_1")
    assert not (outside / "workspaces").exists()


def test_workspace_paths_reject_intra_root_tenant_traversal(tmp_path: Path):
    paths = WorkspacePaths(tmp_path / "storage")
    with pytest.raises(ValueError):
        paths.ensure_run_directories("org_1/../org_2", "sales", "run_1")


def test_seed_b2b_lead_research_workspace_and_adapter(tmp_path: Path):
    from aios.core.workflow import WorkflowNode
    from aios.icm.adapter import ICMStageAdapter
    from aios.icm.workspace import seed_b2b_lead_research_workspace

    ws_dir = seed_b2b_lead_research_workspace(tmp_path, org_id="tenant_a", workspace_id="b2b_lead_research")
    assert (ws_dir / "L0" / "WORKSPACE.md").exists()
    assert (ws_dir / "L1" / "ROUTES.md").exists()
    assert (ws_dir / "L2" / "stages" / "company_research" / "stage.yaml").exists()

    # Test allowed tool execution
    node_ok = WorkflowNode(
        id="node_1",
        tool_name="company_lookup",
        stage_id="company_research",
        workspace_id="b2b_lead_research",
    )
    adapter = ICMStageAdapter(
        node=node_ok,
        storage_root=tmp_path,
        org_id="tenant_a",
        run_id="run_100",
    )
    ctx: dict = {}
    shared: dict = {}
    adapter.pre_execute(ctx, shared)
    assert "icm_context" in ctx
    assert "company_lookup" in adapter.manifest.allowed_tools

    # Test post_execute provenance tracking
    prov = adapter.post_execute(output='{"found": true}', shared=shared)
    assert prov["stage_id"] == "company_research"
    assert "_icm_provenance" in shared
    assert (tmp_path / "tenants" / "tenant_a" / "workspaces" / "b2b_lead_research" / "runs" / "run_100" / "provenance" / "company_research.json").exists()

    # Test tool governance denial
    node_denied = WorkflowNode(
        id="node_2",
        tool_name="crm_update",
        stage_id="company_research",
        workspace_id="b2b_lead_research",
    )
    adapter_denied = ICMStageAdapter(
        node=node_denied,
        storage_root=tmp_path,
        org_id="tenant_a",
        run_id="run_100",
    )
    with pytest.raises(PermissionError, match="explicitly denied"):
        adapter_denied.pre_execute({}, {})
