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


def test_known_schema_validation_rejects_malformed_payloads():
    from aios.icm.schemas import SchemaValidationError, validate_schema

    for sid in (
        "lead_research_input.v1",
        "company_research_output.v1",
        "lead_qualification_output.v1",
        "pet.enquiry.v1",
        "pet.qualified_lead.v1",
        "pet.lead_context.v1",
        "pet.follow_up_result.v1",
        "tool_call.v1",
        "agent_run.v1",
        "memory_candidate.v1",
        "handoff.v1",
        "trace.v1",
    ):
        with pytest.raises(SchemaValidationError):
            validate_schema(sid, ["not", "a", "dict"])
        with pytest.raises(SchemaValidationError):
            validate_schema(sid, 123)


def test_known_schema_validation_accepts_valid_shapes():
    from aios.icm.schemas import validate_schema

    validate_schema("lead_research_input.v1", {"query": "acme"})
    validate_schema("company_research_output.v1", {"company": "Acme", "summary": "ok"})
    validate_schema("lead_qualification_output.v1", {"qualified": True, "score": 80})
    validate_schema("pet.enquiry.v1", {"message": "hi", "phone": "+1"})
    validate_schema("pet.qualified_lead.v1", {"qualified": False, "status": "new"})
    validate_schema("pet.lead_context.v1", {"lead_id": "l1", "phone": "+1"})
    validate_schema("pet.follow_up_result.v1", {"sent": True, "status": "ok"})
    validate_schema("tool_call.v1", {"tool": "lookup", "args": {"q": "x"}})
    validate_schema("agent_run.v1", {"agent_id": "a1", "status": "ok"})
    validate_schema("memory_candidate.v1", {"content": "remember this", "kind": "fact"})
    validate_schema("handoff.v1", {"target": "human", "reason": "needs review"})
    validate_schema("trace.v1", {"event": "step", "trace_id": "t1"})


def test_known_schema_validation_rejects_wrong_types_and_empty_objects():
    from aios.icm.schemas import SchemaValidationError, validate_schema

    with pytest.raises(SchemaValidationError):
        validate_schema("lead_qualification_output.v1", {"qualified": "yes"})
    with pytest.raises(SchemaValidationError):
        validate_schema("tool_call.v1", {"tool": ""})
    with pytest.raises(SchemaValidationError):
        validate_schema("tool_call.v1", {"args": {}})
    with pytest.raises(SchemaValidationError):
        validate_schema("agent_run.v1", {"run_id": "r1"})
    with pytest.raises(SchemaValidationError):
        validate_schema("memory_candidate.v1", {"kind": "fact"})
    with pytest.raises(SchemaValidationError):
        validate_schema("pet.follow_up_result.v1", {"sent": "true"})
    with pytest.raises(SchemaValidationError):
        validate_schema("lead_research_input.v1", {})


def test_adapter_known_schema_validation_fail_closed(tmp_path: Path):
    from aios.core.workflow import WorkflowNode
    from aios.icm.adapter import ICMStageAdapter

    manifest = StageManifest.model_validate({
        "id": "s1", "version": "1.0.0", "mode": "deterministic",
        "inputs_schema": "lead_research_input.v1",
        "outputs_schema": "company_research_output.v1",
    })
    node = WorkflowNode(id="n1", stage_id="s1", stage_manifest=manifest)
    adapter = ICMStageAdapter(node=node, storage_root=tmp_path, org_id="o", run_id="r")

    with pytest.raises(ValueError, match="ICM input schema validation failed"):
        adapter.validate_input(["bad"])
    with pytest.raises(ValueError, match="ICM output schema validation failed"):
        adapter.validate_output(["bad"])

    adapter.validate_input({"query": "acme"})
    adapter.validate_output({"company": "Acme", "summary": "ok"})


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
