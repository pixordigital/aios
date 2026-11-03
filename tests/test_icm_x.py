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
