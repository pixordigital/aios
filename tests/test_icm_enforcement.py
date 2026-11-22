"""ICM-X runtime enforcement: budgets, retries, idempotency, tool gates."""

import pytest

from aios.icm.contracts import RetryPolicy, StageManifest
from aios.icm.enforcement import (
    BudgetExceeded,
    StageBudget,
    ToolDenied,
    check_tool,
    classify_failure,
    idempotency_key,
    side_effect_already_applied,
)


def _manifest(**overrides):
    data = dict(
        id="stage", version="1.0.0", mode="llm", max_llm_calls=2, max_cost_usd=0.02,
        allowed_tools=["company_lookup"], denied_tools=[],
    )
    data.update(overrides)
    return StageManifest.model_validate(data)


def test_budget_blocks_before_exceeding_calls():
    budget = StageBudget.from_manifest(_manifest())
    budget.charge(0.005)
    budget.charge(0.005)
    assert budget.remaining_calls == 0
    with pytest.raises(BudgetExceeded, match="ceiling"):
        budget.charge(0.0)


def test_budget_blocks_cost_overflow_even_under_call_limit():
    budget = StageBudget.from_manifest(_manifest(max_llm_calls=5, max_cost_usd=0.01))
    with pytest.raises(BudgetExceeded, match="cost"):
        budget.charge(0.02)
    assert budget.calls == 0


def test_tool_ceiling_is_enforced():
    budget = StageBudget(max_llm_calls=5, max_cost_usd=0.0, max_tool_calls=2)
    budget.charge_tool()
    budget.charge_tool()
    assert budget.tool_calls == 2
    with pytest.raises(BudgetExceeded, match="tool ceiling"):
        budget.charge_tool()


def test_deterministic_stage_cannot_spend():
    from aios.icm.contracts import StageManifest as SM

    manifest = SM.model_validate({"id": "det", "version": "1.0.0", "mode": "deterministic"})
    budget = StageBudget.from_manifest(manifest)
    with pytest.raises(BudgetExceeded):
        budget.charge(0.0)
    assert budget.max_tool_calls == 1


def test_tool_allow_and_deny():
    manifest = _manifest(denied_tools=[])
    check_tool(manifest, "company_lookup")
    with pytest.raises(ToolDenied, match="allowlist"):
        check_tool(manifest, "crm_update")


def test_retry_classification():
    policy = RetryPolicy(max_attempts=2)
    assert classify_failure("timeout", policy, attempt=1) == "retry"
    assert classify_failure("permission_denied", policy, attempt=1) == "abort"
    assert classify_failure("timeout", policy, attempt=2) == "abort"
    assert classify_failure("unknown_error", policy, attempt=1) == "abort"


def test_idempotency_key_is_stable_and_scoped():
    first = idempotency_key("stage", "task", "send_email")
    assert first == idempotency_key("stage", "task", "send_email")
    assert first != idempotency_key("stage", "task2", "send_email")
    assert side_effect_already_applied({first}, first)
    assert not side_effect_already_applied(set(), first)


def test_adapter_charges_against_declared_budget(tmp_path):
    from aios.core.workflow import WorkflowNode
    from aios.icm.adapter import ICMStageAdapter
    from aios.icm.workspace import seed_b2b_lead_research_workspace

    seed_b2b_lead_research_workspace(tmp_path, org_id="o", workspace_id="b2b_lead_research")
    node = WorkflowNode(id="n1", tool_name="company_lookup", stage_id="company_research",
                        workspace_id="b2b_lead_research")
    adapter = ICMStageAdapter(node=node, storage_root=tmp_path, org_id="o", run_id="r")
    adapter.charge_llm(0.001)
    assert adapter.budget.calls == 1
    prov = adapter.post_execute(output="ok", shared={})
    assert prov["llm_calls"] == 1
