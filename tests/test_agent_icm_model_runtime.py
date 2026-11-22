"""Integration smoke: ICM budget/context ceiling + model runtime eligibility."""
import pytest

from aios.core.agent import AgentRuntime
from aios.db.models import Agent
from aios.governance.model_intelligence import ModelRegistryEntry


def _agent(**overrides):
    data = {
        "id": "agent-icm-model",
        "name": "sdr",
        "org_id": "org-1",
        "llm_config": {"model": "openai/gpt-4o"},
        "tools": ["web_search"],
        "governance_config": {},
        "extra_data": {
            "icm": {"workspace_id": "sales_ops", "stage_id": "sdr_prospecting"},
            "model_policy": {"denied_models": ["openai/gpt-4o"]},
        },
    }
    data.update(overrides)
    return Agent(**data)


def test_icm_stage_and_model_policy_coexist(tmp_path, monkeypatch):
    from aios.config import settings
    from aios.icm.team_workspaces import seed_team_workspaces

    seed_team_workspaces(tmp_path, "org-1", workspaces=["sales_ops"])
    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    rt = AgentRuntime(_agent())
    assert rt.stage is not None
    assert rt._icm_budget.max_llm_calls == rt.stage.manifest.max_llm_calls
    # denied model blocked deterministically
    with pytest.raises(Exception) as exc:
        rt._assert_model_eligible("openai/gpt-4o", rt._org_extra(), None)
    assert "Model policy blocked" in str(exc.value)


def test_icm_context_ceiling_enforced(tmp_path, monkeypatch):
    from aios.config import settings
    from aios.icm.team_workspaces import seed_team_workspaces
    from aios.icm.enforcement import BudgetExceeded

    seed_team_workspaces(tmp_path, "org-1", workspaces=["sales_ops"])
    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    agent = _agent(extra_data={"icm": {"workspace_id": "sales_ops", "stage_id": "sdr_prospecting"}})
    rt = AgentRuntime(agent)
    # stage manifest is a frozen pydantic model; mutate context via model_copy
    rt.stage.manifest = rt.stage.manifest.model_copy(
        update={"context": rt.stage.manifest.context.model_copy(update={"max_context_tokens": 5})}
    )
    with pytest.raises(BudgetExceeded):
        rt._enforce_llm_context_ceiling([{"role": "user", "content": "x" * 200}], 100)


@pytest.mark.asyncio
async def test_registry_policy_blocks_runtime_model(tmp_path, monkeypatch):
    from aios.config import settings
    from aios.icm.team_workspaces import seed_team_workspaces

    seed_team_workspaces(tmp_path, "org-1", workspaces=["sales_ops"])
    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    agent = _agent(extra_data={
        "icm": {"workspace_id": "sales_ops", "stage_id": "sdr_prospecting"},
        "model_policy": {"require_registry_approval": True},
    })
    rt = AgentRuntime(agent)
    entry = ModelRegistryEntry(
        org_id="org-1", model_key="openai/gpt-4o", provider="openai", tier=2,
        capabilities=["tool_use"], approved=True, privacy_ok=True, contract_ok=True,
    )
    ok, reason, _ = __import__("aios.core.router", fromlist=["model_runtime_eligible"]).model_runtime_eligible(
        "openai/gpt-4o", org_extra=agent.extra_data, registry_entries=[entry]
    )
    assert ok, reason
    bad = ModelRegistryEntry(
        org_id="org-1", model_key="openai/gpt-4o", provider="openai", tier=2,
        capabilities=["tool_use"], approved=False, privacy_ok=True, contract_ok=True,
    )
    with pytest.raises(Exception):
        rt._assert_model_eligible("openai/gpt-4o", agent.extra_data, [bad])


@pytest.mark.asyncio
async def test_runtime_registry_load_cached_for_run(tmp_path, monkeypatch):
    from aios.config import settings
    from aios.icm.team_workspaces import seed_team_workspaces

    seed_team_workspaces(tmp_path, "org-1", workspaces=["sales_ops"])
    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    agent = _agent(extra_data={"icm": {"workspace_id": "sales_ops", "stage_id": "sdr_prospecting"}})
    rt = AgentRuntime(agent)

    calls = {"n": 0}

    class _Res:
        def scalars(self):
            return self

        def all(self):
            return [ModelRegistryEntry(org_id="org-1", model_key="openai/gpt-4o", provider="openai", tier=2, approved=True)]

    class _DB:
        async def execute(self, _q):
            calls["n"] += 1
            return _Res()

    first = await rt._load_runtime_registry(_DB())
    second = await rt._load_runtime_registry(_DB())
    assert calls["n"] == 1
    assert first is second
    assert first and first[0].model_key == "openai/gpt-4o"


@pytest.mark.asyncio
async def test_runtime_registry_required_fail_closed_on_load_failure(tmp_path, monkeypatch):
    from aios.config import settings
    from aios.icm.team_workspaces import seed_team_workspaces

    seed_team_workspaces(tmp_path, "org-1", workspaces=["sales_ops"])
    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    agent = _agent(extra_data={
        "icm": {"workspace_id": "sales_ops", "stage_id": "sdr_prospecting"},
        "model_policy": {"require_registry_approval": True},
    })
    rt = AgentRuntime(agent)

    class _BadDB:
        async def execute(self, _q):
            raise RuntimeError("db down")

    entries = await rt._load_runtime_registry(_BadDB())
    assert entries == []
    with pytest.raises(Exception) as exc:
        rt._assert_model_eligible("openai/gpt-4o", agent.extra_data, entries)
    assert "Model policy blocked" in str(exc.value)


def test_agent_runtime_injects_actor_context_hints(tmp_path, monkeypatch):
    from aios.config import settings
    from aios.icm.team_workspaces import seed_team_workspaces

    seed_team_workspaces(tmp_path, "org-1", workspaces=["sales_ops"])
    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    agent = _agent(extra_data={
        "icm": {"workspace_id": "sales_ops", "stage_id": "sdr_prospecting"},
        "actor_context": {
            "actor_user_id": "u-1",
            "actor_departments": ["sales"],
            "is_founder": False,
            "granted_record_ids": ["kr-1"],
        },
    })
    rt = AgentRuntime(agent)
    assert rt.tool_engine.actor_user_id == "u-1"
    assert rt.tool_engine.actor_departments == {"sales"}
    assert rt.tool_engine.granted_record_ids == {"kr-1"}
    assert rt.tool_engine.is_founder is False


@pytest.mark.asyncio
async def test_tool_engine_actor_resolver_used_when_unresolved(monkeypatch):
    from aios.core.tools import ToolEngine, TOOL_REGISTRY
    import aios.core.tools as tools_mod

    class DummyTool:
        @classmethod
        def openai_schema(cls):
            return {"type": "function", "function": {"name": "dummy_actor_resolver", "parameters": {"type": "object"}}}

        async def run(self):
            return {
                "actor_user_id": getattr(self, "_actor_user_id", ""),
                "depts": sorted(getattr(self, "_actor_departments", [])),
            }

    TOOL_REGISTRY["dummy_actor_resolver"] = {
        "code_reference": "aios.tools.calculator.DummyActorResolver",
        "description": "d",
    }
    monkeypatch.setattr(tools_mod, "_ALLOWED_MODULES", set(tools_mod._ALLOWED_MODULES) | {"aios.tools.calculator"})

    async def resolver():
        return {"actor_user_id": "u-res", "actor_departments": ["sales"], "granted_record_ids": []}

    engine = ToolEngine([], org_id="org-1", agent_id="agent-1", actor_resolver=resolver)
    engine.tools["dummy_actor_resolver"] = DummyTool()
    out = await engine.execute("dummy_actor_resolver", "{}")
    import json
    data = json.loads(out)
    assert data["actor_user_id"] == "u-res"
    assert data["depts"] == ["sales"]


@pytest.mark.asyncio
async def test_tool_engine_execute_stamps_actor_context(monkeypatch):
    from aios.core.tools import ToolEngine, TOOL_REGISTRY

    class DummyTool:
        name = "dummy_actor_tool"
        description = "d"

        @classmethod
        def openai_schema(cls):
            return {"type": "function", "function": {"name": "dummy_actor_tool", "parameters": {"type": "object"}}}

        async def run(self):
            return {
                "actor_user_id": getattr(self, "_actor_user_id", ""),
                "depts": sorted(getattr(self, "_actor_departments", [])),
                "granted": sorted(getattr(self, "_granted_record_ids", [])),
                "resolved": getattr(self, "_actor_resolved", False),
            }

    TOOL_REGISTRY["dummy_actor_tool"] = {
        "code_reference": "aios.tools.dynamic.DummyActorTool",
        "description": "d",
    }
    engine = ToolEngine.__new__(ToolEngine)
    engine.tools = {"dummy_actor_tool": DummyTool()}
    engine.org_id = "org-1"
    engine.agent_id = "agent-1"
    engine.actor_user_id = ""
    engine.actor_departments = set()
    engine.is_founder = False
    engine.granted_record_ids = set()
    engine.actor_resolver = None
    engine._actor_resolved = False
    engine.missing = []

    # avoid allow-list/module checks by patching registry/module gate minimally
    monkeypatch.setitem(TOOL_REGISTRY["dummy_actor_tool"], "code_reference", "aios.tools.calculator.DummyActorTool")
    import aios.core.tools as tools_mod
    monkeypatch.setattr(tools_mod, "_ALLOWED_MODULES", set(tools_mod._ALLOWED_MODULES) | {"aios.tools.calculator"})

    engine.set_actor_context(actor_user_id="u-9", actor_departments={"ops"}, granted_record_ids={"kr9"})
    out = await engine.execute("dummy_actor_tool", "{}")
    import json
    data = json.loads(out)
    assert data["actor_user_id"] == "u-9"
    assert data["depts"] == ["ops"]
    assert data["granted"] == ["kr9"]
    assert data["resolved"] is True
