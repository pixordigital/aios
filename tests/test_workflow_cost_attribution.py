"""Workflow nodes must attribute paid calls to the ICM stage budget."""
import json
from types import SimpleNamespace

import pytest

from aios.core import workflow
from aios.core.workflow import (
    WorkflowDef,
    WorkflowEngine,
    WorkflowNode,
    WorkflowResult,
)
from aios.icm.contracts import StageManifest
from aios.icm.enforcement import StageBudget


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, model, agent_id):
        return SimpleNamespace(
            id=agent_id,
            name="agent",
            llm_config={"model": "openai/gpt-4o"},
            system_prompt="",
            tools=[],
            memory_config={},
            governance_config={"autonomous": False},
            extra_data={},
            org_id="o1",
            status="active",
        )


class FakeRuntime:
    def __init__(self, *args, **kwargs):
        self._icm_budget = SimpleNamespace(cost_usd=0.0123, calls=2)

    async def run(self, conv_id, message):
        return "done"


class FakeAdapter:
    instances = []

    def __init__(self, **kwargs):
        self.node = kwargs["node"]
        self.manifest = self.node.stage_manifest
        self.budget = StageBudget(
            max_llm_calls=3, max_cost_usd=0.05, max_tool_calls=3
        )
        self.charges = []
        FakeAdapter.instances.append(self)

    def pre_execute(self, ctx, shared):
        pass

    def enforce_execution(self, shared, action=None):
        pass

    def validate_output(self, output):
        pass

    def charge_llm(self, cost_usd=0.0):
        self.budget.charge(cost_usd)
        self.charges.append(cost_usd)

    def post_execute(self, output, shared):
        return {
            "stage_id": "cost-stage",
            "llm_calls": self.budget.calls,
            "cost_usd": self.budget.cost_usd,
        }


@pytest.mark.asyncio
async def test_agent_node_charges_actual_runtime_cost(monkeypatch):
    FakeAdapter.instances.clear()
    monkeypatch.setattr("aios.db.engine.async_session", lambda: FakeSession())
    monkeypatch.setattr(workflow, "AgentRuntime", FakeRuntime)
    monkeypatch.setattr("aios.icm.adapter.ICMStageAdapter", FakeAdapter)

    manifest = StageManifest(
        id="cost-stage",
        version="1.0.0",
        mode="llm",
        max_llm_calls=3,
        max_cost_usd=0.05,
    )
    node = WorkflowNode(id="n1", agent_id="a1", stage_manifest=manifest)
    result = WorkflowResult()

    await WorkflowEngine()._execute_node(node, "conv-1", {}, result)

    assert result.ok(), result.errors
    adapter = FakeAdapter.instances[-1]
    assert adapter.charges == [0.0123], adapter.charges
    provenance = json.loads(result.outputs["n1_icm_provenance"])
    assert provenance["llm_calls"] == 1
    assert provenance["cost_usd"] == pytest.approx(0.0123)


@pytest.mark.asyncio
async def test_agent_node_refuses_when_stage_call_ceiling_spent(monkeypatch):
    FakeAdapter.instances.clear()
    monkeypatch.setattr("aios.db.engine.async_session", lambda: FakeSession())
    monkeypatch.setattr(workflow, "AgentRuntime", FakeRuntime)

    class SpentAdapter(FakeAdapter):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            for _ in range(3):
                self.budget.charge(0.001)

    monkeypatch.setattr("aios.icm.adapter.ICMStageAdapter", SpentAdapter)

    manifest = StageManifest(
        id="cost-stage",
        version="1.0.0",
        mode="llm",
        max_llm_calls=3,
        max_cost_usd=0.05,
    )
    node = WorkflowNode(id="n1", agent_id="a1", stage_manifest=manifest)
    result = WorkflowResult()

    with pytest.raises(Exception, match="LLM call ceiling reached"):
        await WorkflowEngine()._execute_node(node, "conv-1", {}, result)

    assert result.node_status["n1"] == "running"
