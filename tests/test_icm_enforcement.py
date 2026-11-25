"""ICM-X runtime enforcement: budgets, retries, idempotency, tool gates."""

import pytest

from aios.icm.contracts import RetryPolicy, StageManifest, manifest_fingerprint
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


def _approved_session(tmp_path, *, approval_id="appr-42", org_id="o", status="approved", decided_by="founder-1"):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from aios.db.models import PendingAction

    engine = create_engine(f"sqlite:///{tmp_path / 'approvals.db'}")
    PendingAction.__table__.create(engine)
    session = Session(engine)
    session.add(
        PendingAction(
            id=approval_id,
            org_id=org_id,
            agent_id="agent-1",
            conversation_id="conv-1",
            tool_name="company_lookup",
            tool_args={},
            status=status,
            decided_by=decided_by,
        )
    )
    session.commit()
    return session


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


def test_adapter_approval_required_fails_closed():
    from aios.core.workflow import WorkflowNode
    from aios.icm.adapter import ICMStageAdapter

    manifest = _manifest(approval_required=True, id="needs_approval")
    node = WorkflowNode(id="n1", tool_name="company_lookup", stage_id="needs_approval", stage_manifest=manifest)
    adapter = ICMStageAdapter(node=node, storage_root="data", org_id="o", run_id="r")
    with pytest.raises(PermissionError, match="requires approval"):
        adapter.enforce_execution({}, action="company_lookup")


def test_adapter_injects_explicit_preapproved_marker(tmp_path):
    from aios.core.workflow import WorkflowNode
    from aios.icm.adapter import ICMStageAdapter

    manifest = _manifest(approval_required=True, id="needs_approval")
    fp = manifest_fingerprint(manifest)
    node = WorkflowNode(id="n1", tool_name="company_lookup", stage_id="needs_approval", stage_manifest=manifest)
    session = _approved_session(tmp_path)
    adapter = ICMStageAdapter(
        node=node,
        storage_root="data",
        org_id="o",
        run_id="r",
        preapproved={
            "approved": True,
            "approval_id": "appr-42",
            "approved_fingerprint": fp,
            "actions": ["company_lookup"],
        },
        db_session=session,
    )
    shared = {}
    adapter.enforce_execution(shared, action="company_lookup")
    assert shared["icm_approval"]["source"] == "icm_preapproved"
    assert shared["icm_approval"]["approval_id"] == "appr-42"
    assert shared["icm_approval"]["approved_fingerprint"] == fp
    assert adapter.approval_bound["approval_id"] == "appr-42"
    session.close()


def test_adapter_rejects_preapproved_wrong_action_or_fingerprint(tmp_path):
    from aios.core.workflow import WorkflowNode
    from aios.icm.adapter import ICMStageAdapter

    manifest = _manifest(approval_required=True, id="needs_approval")
    fp = manifest_fingerprint(manifest)
    node = WorkflowNode(id="n1", tool_name="company_lookup", stage_id="needs_approval", stage_manifest=manifest)
    session = _approved_session(tmp_path, approval_id="appr-1")

    def adapter_with(marker):
        return ICMStageAdapter(
            node=node,
            storage_root="data",
            org_id="o",
            run_id="r",
            preapproved=marker,
            db_session=session,
        )

    markers = [
        {"approved": True, "approval_id": "appr-1", "approved_fingerprint": fp, "actions": ["other_tool"]},
        {"approved": True, "approval_id": "appr-1", "approved_fingerprint": "bad", "actions": ["company_lookup"]},
        {"approved": True, "approved_fingerprint": fp, "actions": ["company_lookup"]},
        {"approved": True, "approval_id": "appr-1", "actions": ["company_lookup"]},
        {"approved": True, "actions": ["company_lookup"]},
    ]
    for marker in markers:
        with pytest.raises(PermissionError, match="requires approval"):
            adapter_with(marker).enforce_execution({}, action="company_lookup")
    session.close()


@pytest.mark.parametrize(
    "row_kwargs",
    [{"org_id": "other"}, {"status": "pending"}, {"decided_by": None}],
)
def test_adapter_rejects_unbacked_db_approval_marker(tmp_path, row_kwargs):
    from aios.core.workflow import WorkflowNode
    from aios.icm.adapter import ICMStageAdapter

    manifest = _manifest(approval_required=True, id="needs_approval")
    fp = manifest_fingerprint(manifest)
    node = WorkflowNode(id="n1", tool_name="company_lookup", stage_id="needs_approval", stage_manifest=manifest)
    session = _approved_session(tmp_path, approval_id="appr-db", **row_kwargs)
    adapter = ICMStageAdapter(
        node=node,
        storage_root="data",
        org_id="o",
        run_id="r",
        preapproved={
            "approved": True,
            "approval_id": "appr-db",
            "approved_fingerprint": fp,
            "actions": ["company_lookup"],
        },
        db_session=session,
    )
    with pytest.raises(PermissionError, match="requires approval"):
        adapter.enforce_execution({}, action="company_lookup")
    session.close()


def test_adapter_fails_closed_on_unsupported_context_layers(tmp_path):
    from aios.core.workflow import WorkflowNode
    from aios.icm.adapter import ICMStageAdapter
    from aios.icm.workspace import WorkspacePaths

    WorkspacePaths(tmp_path).ensure_workspace_scaffold("o", "b2b_lead_research")
    manifest = _manifest(context={"layers": ["identity", "dynamic_references"]})
    node = WorkflowNode(
        id="n1", tool_name="company_lookup", stage_id="stage",
        workspace_id="b2b_lead_research", stage_manifest=manifest,
    )
    adapter = ICMStageAdapter(node=node, storage_root=tmp_path, org_id="o", run_id="r")
    with pytest.raises(ValueError, match="unsupported context layers"):
        adapter.pre_execute({}, {})


def test_adapter_post_execute_reports_disk_write_failure(tmp_path, monkeypatch, caplog):
    import logging

    from aios.core.workflow import WorkflowNode
    from aios.icm.adapter import ICMStageAdapter
    from aios.icm.workspace import WorkspacePaths

    node = WorkflowNode(id="n1", stage_id="stage", stage_manifest=_manifest())
    adapter = ICMStageAdapter(node=node, storage_root=tmp_path, org_id="o", run_id="r")

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(WorkspacePaths, "ensure_run_directories", fail)
    with caplog.at_level(logging.WARNING, logger="aios.icm.adapter"):
        prov = adapter.post_execute("ok", {})
    assert prov["disk_write_error"] == "disk full"
    assert "Failed saving ICM-X provenance files" in caplog.text
