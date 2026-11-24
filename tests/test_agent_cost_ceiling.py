"""Fail-closed cost ceiling for agents with no ICM stage binding."""

import pytest
from pydantic import ValidationError

from aios.config import Settings, settings
from aios.core.agent import AgentRuntime
from aios.db.models import Agent
from aios.icm.contracts import StageManifest
from aios.icm.enforcement import BudgetExceeded


def _agent(**overrides) -> Agent:
    data = {
        "id": "agent-ceiling",
        "name": "unbound-worker",
        "org_id": "org-1",
        "llm_config": {"model": "openai/gpt-4o"},
        "tools": [],
        "governance_config": {"max_tool_calls_per_run": 2},
        "extra_data": {},
    }
    data.update(overrides)
    return Agent(**data)


def test_default_unbound_ceiling_is_finite_and_positive(monkeypatch):
    monkeypatch.delenv("AIOS_UNBOUND_AGENT_MAX_COST_USD", raising=False)

    value = Settings(_env_file=None).unbound_agent_max_cost_usd

    assert 0.0 < value < float("inf")


def test_unbound_ceiling_env_override(monkeypatch):
    monkeypatch.setenv("AIOS_UNBOUND_AGENT_MAX_COST_USD", "0.25")

    assert Settings(_env_file=None).unbound_agent_max_cost_usd == 0.25


def test_non_finite_unbound_ceiling_is_rejected(monkeypatch):
    monkeypatch.setenv("AIOS_UNBOUND_AGENT_MAX_COST_USD", "inf")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_unbound_agent_uses_settings_ceiling(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "unbound_agent_max_cost_usd", 0.25)

    runtime = AgentRuntime(_agent())

    assert runtime.stage is None
    budget = runtime._icm_budget
    assert budget.max_cost_usd == 0.25
    assert budget.max_llm_calls == runtime.MAX_ITERATIONS
    assert budget.max_tool_calls == 2
    budget.charge(0.25)
    with pytest.raises(BudgetExceeded, match="cost ceiling"):
        budget.charge(0.0)


def test_bound_agent_keeps_manifest_ceiling(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "unbound_agent_max_cost_usd", 42.0)
    manifest = StageManifest.model_validate({
        "id": "cost_stage",
        "version": "1.0.0",
        "mode": "llm",
        "max_llm_calls": 2,
        "max_cost_usd": 0.35,
    })
    agent = _agent(extra_data={"icm": {"stage_manifest": manifest.model_dump(mode="json")}})

    runtime = AgentRuntime(agent)

    assert runtime.stage is not None
    assert runtime._icm_budget.max_cost_usd == runtime.stage.manifest.max_cost_usd == 0.35
    assert runtime._icm_budget.max_llm_calls == 2
