"""ICM coverage for business teams outside the original sales/dev/security fleet."""
import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace

from aios.icm.contracts import load_stage_manifest
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
