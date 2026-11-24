"""ICM coverage for business teams outside the original sales/dev/security fleet."""
import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from aios.icm.adapter import ICMStageAdapter
from aios.icm.contracts import load_stage_manifest, manifest_fingerprint
from aios.icm.team_workspaces import (
    AGENT_EVENTS,
    AGENT_STAGES,
    TEAM_WORKSPACES,
    seed_team_workspaces,
)
from aios.templates import apply_template

ROOT = Path(__file__).resolve().parents[1]

NEW_WORKSPACES = {
    "media_ops",
    "marketing_ops",
    "customer_success_ops",
    "revops_ops",
}

# Exact prod agent names -> template that supplies their configured tools.
PROD_AGENTS = {
    "Media Manager": "media_manager",
    "Market Intelligence Researcher": "market_intelligence",
    "Content Strategist": "content_strategist",
    "Content Producer": "content_producer",
    "Marketing": "marketing",
    "Manager Marketing": "manager_marketing",
    "Customer Success": "customer_success",
    "Manager Cs": "manager_cs",
    "Support": "support",
    "Revops": "revops",
    "Manager Revops": "manager_revops",
    "Deal Auditor": "deal_auditor",
    "Evidence Compiler": "evidence_compiler",
    "Human Auditor Assistant": "human_auditor",
    "Pricing Guardian": "pricing_guardian",
    "Performance Watcher": "performance_watcher",
}

EVENT_SOURCES = (
    "aios/core/events.py",
    "aios/tasks/jobs.py",
    "aios/core/cron_scheduler.py",
    "aios/core/deployment.py",
    "aios/api/crm2.py",
)
EVENT_PUBLISH = re.compile(
    r"""\b(?:publish|publish_event|publish_many)\(\s*f?["']([a-z][a-z0-9_.{}]*)["']"""
)

# Exact fleet bindings: any other agent has no real producer and stays
# request/board-driven.
EXPECTED_AGENT_EVENTS = {
    "sales-sdr": ["message.received"],
    "sales-closer": ["crm.deal_stalled", "sales.drop_detected", "crm.stage_changed.*"],
    "sales-manager": ["crm.deal_stalled", "sales.drop_detected", "crm.stage_changed.*"],
    "Support": ["message.received"],
}
AUDIT_ONLY_ACTIONS = {"agent.deploy_failed", "agent.verify_failed"}


def _stage_path(root: Path, workspace: str, stage: str) -> Path:
    return (
        root / "tenants" / "org-1" / "workspaces" / workspace
        / "L2" / "stages" / stage / "stage.yaml"
    )


def _published_event_types() -> set[str]:
    produced: set[str] = set()
    for relative_path in EVENT_SOURCES:
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        produced.update(EVENT_PUBLISH.findall(text))
    return produced


def _load_provisioner():
    path = ROOT / "scripts" / "provision_icm_fleet.py"
    spec = importlib.util.spec_from_file_location("provision_icm_fleet", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _side_effect_adapter(tmp_path: Path, manifest, marker=None):
    workspace_id, stage_id = AGENT_STAGES["sales-closer"]
    node = SimpleNamespace(
        id=stage_id,
        stage_id=stage_id,
        workspace_id=workspace_id,
        stage_manifest=manifest,
    )
    return ICMStageAdapter(
        node,
        storage_root=str(tmp_path),
        org_id="org-1",
        run_id="approval-test",
        workspace_id=workspace_id,
        preapproved=marker,
    )


def test_four_business_workspaces_seed(tmp_path: Path):
    written = seed_team_workspaces(tmp_path, "org-1")

    assert len(TEAM_WORKSPACES) == 10
    assert NEW_WORKSPACES <= set(TEAM_WORKSPACES)
    assert len(written) == len(TEAM_WORKSPACES)
    for workspace_id in NEW_WORKSPACES:
        ws_dir = tmp_path / "tenants" / "org-1" / "workspaces" / workspace_id
        assert (ws_dir / "L0" / "WORKSPACE.md").is_file()
        assert (ws_dir / "L1" / "ROUTES.md").is_file()
        assert list(ws_dir.glob("L2/stages/*/stage.yaml"))


def test_prod_agents_bound_to_new_stages(tmp_path: Path):
    seed_team_workspaces(tmp_path, "org-1")

    assert len(PROD_AGENTS) == 16
    assert set(PROD_AGENTS) <= set(AGENT_STAGES)
    for name in PROD_AGENTS:
        workspace_id, stage_id = AGENT_STAGES[name]
        assert workspace_id in NEW_WORKSPACES
        assert stage_id in TEAM_WORKSPACES[workspace_id]["stages"]
        assert _stage_path(tmp_path, workspace_id, stage_id).is_file(), name


def test_new_stage_manifests_valid_and_tools_match_agents(tmp_path: Path):
    seed_team_workspaces(tmp_path, "org-1")

    for name, template_key in PROD_AGENTS.items():
        workspace_id, stage_id = AGENT_STAGES[name]
        manifest = load_stage_manifest(_stage_path(tmp_path, workspace_id, stage_id))

        assert manifest.version == "1.0.0"
        assert manifest.mode == "llm"
        assert manifest.max_llm_calls > 0
        assert manifest.max_cost_usd > 0
        assert manifest.allowed_tools
        assert not set(manifest.allowed_tools) & set(manifest.denied_tools)
        configured = set(apply_template(template_key)["tools"])
        assert set(manifest.allowed_tools) <= configured, name


def test_side_effecting_stages_declare_approval_required(tmp_path: Path):
    seed_team_workspaces(tmp_path, "org-1")

    checked = 0
    for workspace_id, workspace in TEAM_WORKSPACES.items():
        for stage_id, stage in workspace["stages"].items():
            if not stage["side_effects"]:
                continue
            manifest = load_stage_manifest(_stage_path(tmp_path, workspace_id, stage_id))
            assert manifest.side_effects is True
            assert manifest.approval_required is True, (workspace_id, stage_id)
            checked += 1
    assert checked == 7


def test_event_subscriptions_have_real_publishers():
    produced = _published_event_types()
    published_prefixes = {event.split("{", 1)[0] for event in produced}

    assert AGENT_EVENTS == EXPECTED_AGENT_EVENTS
    assert set(AGENT_EVENTS) <= set(AGENT_STAGES)
    assert {
        "message.received",
        "agent.workday_completed",
        "agent.proactive_completed",
        "crm.deal_stalled",
        "sales.drop_detected",
        "crm.stage_changed.{new_stage}",
    } <= produced
    # deployment.py writes audit actions, not bus events.
    assert AUDIT_ONLY_ACTIONS.isdisjoint(produced)

    for name, events in AGENT_EVENTS.items():
        assert not AUDIT_ONLY_ACTIONS.intersection(events), name
        for event in events:
            if event.endswith("*"):
                assert any(p.startswith(event[:-1]) for p in published_prefixes), (name, event)
            else:
                assert event in produced, (name, event)
    # Only the reactive agent among the business fleet subscribes; the rest
    # stay request/board-driven.
    assert {name for name in PROD_AGENTS if name in AGENT_EVENTS} == {"Support"}


def test_provisioner_extra_data_converges():
    provisioner = _load_provisioner()
    stale = {"event_subscriptions": ["agent.deploy_failed"], "keep": True}

    first = provisioner._agent_extra(
        SimpleNamespace(name="Customer Success", extra_data=dict(stale)),
        "customer_success_ops",
        "renewal_follow_up",
    )
    second = provisioner._agent_extra(
        SimpleNamespace(name="Customer Success", extra_data=first),
        "customer_success_ops",
        "renewal_follow_up",
    )

    assert first == second
    assert first["keep"] is True
    assert first["icm"] == {
        "workspace_id": "customer_success_ops",
        "stage_id": "renewal_follow_up",
    }
    assert "event_subscriptions" not in first

    for name, workspace_id, stage_id in (
        ("sales-sdr", "sales_ops", "sdr_prospecting"),
        ("Support", "customer_success_ops", "support_reply"),
    ):
        subscribed = provisioner._agent_extra(
            SimpleNamespace(name=name, extra_data={}),
            workspace_id,
            stage_id,
        )
        assert subscribed["event_subscriptions"] == AGENT_EVENTS[name]


def test_provisioner_accepts_supplied_fingerprint_matched_approval(tmp_path: Path):
    seed_team_workspaces(tmp_path, "org-1")
    workspace_id, stage_id = AGENT_STAGES["sales-closer"]
    manifest = load_stage_manifest(_stage_path(tmp_path, workspace_id, stage_id))
    fingerprint = manifest_fingerprint(manifest)
    approvals_file = tmp_path / "approvals.json"
    approvals_file.write_text(
        json.dumps({
            "sales-closer": {
                "approval_id": "appr-founder-1",
                "approved_fingerprint": fingerprint,
                "actions": [stage_id],
                "approved_by": "founder",
            },
            "sales-sdr": {
                "approval_id": "appr-other",
                "approved_fingerprint": "not-this-stage",
                "actions": [stage_id],
                "approved_by": "founder",
            },
        }),
        encoding="utf-8",
    )

    provisioner = _load_provisioner()
    approvals = provisioner._load_approvals(str(approvals_file))
    extra = provisioner._agent_extra(
        SimpleNamespace(name="sales-closer", extra_data={}),
        workspace_id,
        stage_id,
        approvals,
        fingerprint,
    )
    marker = extra["icm"]["preapproved"]

    assert marker["approval_id"] == "appr-founder-1"
    assert marker["approved_by"] == "founder"
    assert marker["approved_fingerprint"] == fingerprint
    assert marker["actions"] == [stage_id]
    other = provisioner._agent_extra(
        SimpleNamespace(name="sales-sdr", extra_data={}),
        workspace_id,
        stage_id,
        approvals,
        fingerprint,
    )
    assert "preapproved" not in other["icm"]

    adapter = _side_effect_adapter(tmp_path, manifest, marker)
    adapter.enforce_execution({}, action="agent_run")
    assert adapter.approval_bound["approval_id"] == "appr-founder-1"


def test_provisioner_without_approvals_scrubs_marker_and_blocks_side_effects(tmp_path: Path):
    seed_team_workspaces(tmp_path, "org-1")
    workspace_id, stage_id = AGENT_STAGES["sales-closer"]
    manifest = load_stage_manifest(_stage_path(tmp_path, workspace_id, stage_id))
    stale = {
        "icm": {
            "workspace_id": workspace_id,
            "stage_id": stage_id,
            "preapproved": {
                "approved": True,
                "approval_id": "fabricated",
                "approved_fingerprint": manifest_fingerprint(manifest),
                "actions": [stage_id],
            },
        },
        "keep": True,
    }

    provisioner = _load_provisioner()
    extra = provisioner._agent_extra(
        SimpleNamespace(name="sales-closer", extra_data=stale),
        workspace_id,
        stage_id,
        provisioner._load_approvals(None),
        None,
    )

    assert "preapproved" not in extra["icm"]
    assert extra["keep"] is True
    with pytest.raises(FileNotFoundError):
        provisioner._load_approvals(str(tmp_path / "missing.json"))
    with pytest.raises(PermissionError, match="requires approval"):
        _side_effect_adapter(
            tmp_path, manifest, extra["icm"].get("preapproved")
        ).enforce_execution({}, action="agent_run")


def test_provisioner_rejects_wrong_fingerprint_approval(tmp_path: Path):
    seed_team_workspaces(tmp_path, "org-1")
    workspace_id, stage_id = AGENT_STAGES["sales-closer"]
    manifest = load_stage_manifest(_stage_path(tmp_path, workspace_id, stage_id))
    approvals_file = tmp_path / "wrong-fingerprint.json"
    approvals_file.write_text(
        json.dumps({
            "sales-closer": {
                "approval_id": "appr-wrong",
                "approved_fingerprint": "0" * 64,
                "actions": [stage_id],
                "approved_by": "founder",
            }
        }),
        encoding="utf-8",
    )
    stale = {
        "icm": {
            "workspace_id": workspace_id,
            "stage_id": stage_id,
            "preapproved": {"approval_id": "fabricated"},
        }
    }

    provisioner = _load_provisioner()
    extra = provisioner._agent_extra(
        SimpleNamespace(name="sales-closer", extra_data=stale),
        workspace_id,
        stage_id,
        provisioner._load_approvals(str(approvals_file)),
        manifest_fingerprint(manifest),
    )

    assert "preapproved" not in extra["icm"]
    assert "fabricated" not in json.dumps(extra)
    with pytest.raises(PermissionError, match="requires approval"):
        _side_effect_adapter(
            tmp_path, manifest, extra["icm"].get("preapproved")
        ).enforce_execution({}, action="agent_run")
