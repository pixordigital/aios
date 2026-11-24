"""Fleet activation readiness — every template must pass the real deploy gate offline.

Provider calls are replaced at the AgentRuntime seam; no paid provider is called.
Credential presence stays a deploy-time gate (`deploy_agents.py --apply`).
"""

import asyncio
import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import aios.core.agent as agent_module
import aios.core.providers as providers
from aios.config import settings
from aios.core import deployment
from aios.core.agent_health import health_tracker
from aios.core.tools import ToolEngine
from aios.core.org_bootstrap import BUSINESS_TEAMS
from aios.db.models import Agent, AgentInstance
from aios.icm.team_workspaces import AGENT_EVENTS, AGENT_STAGES
from aios.media_growth import PHASE1_ROLES
from aios.templates import TEMPLATES, apply_template

NAMES = sorted(TEMPLATES)

# Canonical fleet names (ICM stage bindings) -> template used to seed each row.
SEED_TEMPLATE_BY_NAME = {
    "sales-sdr": "sdr",
    "sales-closer": "closer",
    "sales-manager": "manager_sales",
    "dev-frontend": "frontend",
    "dev-backend": "backend",
    "dev-manager": "manager_dev",
    "red-agent": "red",
    "blue-agent": "blue",
    "security-manager": "manager_red",
    "Data Analyst": "data_analyst",
    "Data Scientist": "data_scientist",
    "data-manager": "manager_data",
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
    "Coordenador Geral": "orchestrator_business",
}


def _agent_for(template, org_id, name=None):
    cfg = apply_template(template)
    return Agent(
        org_id=org_id,
        name=name or template,
        agent_type=cfg["agent_type"],
        system_prompt=cfg["system_prompt"],
        llm_config=cfg["llm_config"],
        tools=cfg["tools"],
        memory_config=cfg.get("memory_config", {}),
        governance_config=cfg.get("governance_config", {}),
        status="draft",
    )


@pytest.mark.parametrize("name", NAMES)
def test_template_passes_activation_static_gate(name):
    """probe_agent runs this before spending a provider call."""
    cfg = apply_template(name)
    agent = SimpleNamespace(
        id=f"tpl-{name}",
        org_id="org-readiness",
        system_prompt=cfg["system_prompt"],
        llm_config=cfg["llm_config"],
        tools=cfg["tools"],
        governance_config=cfg.get("governance_config", {}),
    )
    deployment._static_checks(agent)


def test_seed_inventory_covers_known_fleet_sources():
    inventory = set(SEED_TEMPLATE_BY_NAME)
    assert inventory == set(AGENT_STAGES) | {"Coordenador Geral"}
    assert set(AGENT_EVENTS) <= inventory
    assert set(PHASE1_ROLES) <= inventory
    assert {t["worker"] for t in BUSINESS_TEAMS} <= set(SEED_TEMPLATE_BY_NAME.values())
    assert {t["manager"] for t in BUSINESS_TEAMS} <= set(SEED_TEMPLATE_BY_NAME.values())
    assert all(template in TEMPLATES for template in SEED_TEMPLATE_BY_NAME.values())


def test_seed_inventory_passes_deploy_credential_preflight(monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    cli = importlib.import_module("deploy_agents")

    # Isolate the offline check: no registry DB lookup and no real secret.
    monkeypatch.setattr(providers, "_circuits", {})
    monkeypatch.setattr(providers, "enforce_model_runtime_policy", lambda *_a, **_k: {})
    monkeypatch.setattr(cli.settings, "openrouter_api_key", "offline-probe-key")

    models = [
        apply_template(template)["llm_config"]["model"]
        for template in SEED_TEMPLATE_BY_NAME.values()
    ]
    checked, missing = cli._credential_preflight(models)

    assert missing == []
    assert all(checked[model]["credentials_configured"] is True for model in models)
    assert all(checked[model]["available"] is True for model in models)


class _FakeLLM:
    async def chat_retry(self, **_kwargs):
        return {"content": "OK"}


class _FakeRuntime:
    def __init__(self, _agent):
        self.llm = _FakeLLM()


@pytest.mark.asyncio
async def test_every_seed_agent_activates_with_working_provider(
    monkeypatch, test_db_session, test_org
):
    monkeypatch.setattr(agent_module, "AgentRuntime", _FakeRuntime)
    # Module-level semaphore binds to the first loop that acquires it.
    monkeypatch.setattr(deployment, "_PROBE_SLOTS", asyncio.Semaphore(2))
    monkeypatch.setattr(deployment.settings, "internal_mode", True)

    for name, template in sorted(SEED_TEMPLATE_BY_NAME.items()):
        agent = _agent_for(template, test_org.id, name=name)
        test_db_session.add(agent)
        await test_db_session.commit()

        engine = ToolEngine(agent.tools, org_id=test_org.id, agent_id=agent.id)
        assert engine.missing == [], (name, engine.missing)
        assert set(engine.tools) == set(agent.tools), name

        health_tracker.reset(agent.id)
        try:
            result = await deployment.deploy_and_verify(
                test_db_session, agent, test_org.id, user_id="readiness-test"
            )
        finally:
            health_tracker.reset(agent.id)

        assert agent.status == "active", name
        assert result["evidence"]["reply"] == "OK", name
        inst = (
            await test_db_session.execute(
                select(AgentInstance).where(AgentInstance.agent_id == agent.id)
            )
        ).scalars().one()
        assert inst.status == "running", name
        assert inst.extra_data["verified"] is True, name


@pytest.mark.skipif(
    os.getenv("AIOS_FLEET_LIVE_PROBE") != "1",
    reason="opt-in: spends real provider calls",
)
@pytest.mark.asyncio
async def test_live_probe_seed_inventory(monkeypatch):
    key = os.getenv("AIOS_OPENROUTER_API_KEY") or settings.openrouter_api_key
    if not key or key.startswith("your-"):
        pytest.skip("real AIOS_OPENROUTER_API_KEY required")
    monkeypatch.setattr(settings, "openrouter_api_key", key)

    for name, template in sorted(SEED_TEMPLATE_BY_NAME.items()):
        agent = _agent_for(template, "live-probe", name=name)
        evidence = await deployment.probe_agent(agent)
        assert evidence["reply"].strip(), name
