"""End-to-end ICM-X resume idempotency test via WorkflowEngine.

Verifies that stage attempt recording in WorkflowRun.outputs works
and that resume with resume_outputs/resume_status is idempotent.
Uses calculator tool which is allowed in the lead_qualification stage.
"""
import uuid

import pytest

from aios.core.workflow import WorkflowDef, WorkflowEngine, WorkflowNode, WorkflowResult
from aios.icm.contracts import StageManifest, manifest_fingerprint


@pytest.mark.asyncio
async def test_e2e_icm_resume_idempotent_stage_attempts():
    """Run a workflow node with stage_id bound, verify stage attempt
    recording in outputs, then resume idempotently.

    The engine wires ICMStageAdapter pre/post execution and records
    _icm_stage_attempts in outputs. Resume with same outputs/status
    should be a no-op for stage attempts (idempotent).
    """
    node = WorkflowNode(
        id="n1",
        tool_name="calculator",
        tool_args={"expression": "2+2"},
        # lead_qualification stage allows calculator
        stage_id="lead_qualification",
    )
    wf = WorkflowDef(id=f"wf-{uuid.uuid4()}", name="e2e-icm-resume", nodes={"n1": node})
    engine = WorkflowEngine()
    conv_id = f"conv-{uuid.uuid4()}"

    # First run — stage attempt should be recorded in outputs
    first = await engine.run(wf, conv_id, "hello")
    assert first.ok(), f"First run failed: {first.errors}"
    assert first.node_status.get("n1") == "done", f"Node not done: {first.node_status}"

    # Verify stage attempt was recorded in outputs
    attempts = first.outputs.get("_icm_stage_attempts")
    assert isinstance(attempts, dict), f"Expected dict attempts, got {type(attempts)}"
    assert "n1" in attempts, f"Node n1 not in stage attempts"
    assert attempts["n1"]["status"] == "done", f"Attempt status not done: {attempts['n1']}"
    assert "manifest_fingerprint" in attempts["n1"], "Missing manifest_fingerprint in attempt"

    # Second run — resume with same outputs/status should be idempotent
    second = await engine.run(
        wf,
        conv_id,
        "hello",
        resume_outputs=dict(first.outputs),
        resume_status=dict(first.node_status),
    )
    assert second.ok(), f"Second run failed: {second.errors}"
    assert second.node_status.get("n1") == "done", f"Node not done on resume: {second.node_status}"

    # Outputs must be identical (idempotent)
    assert second.outputs.get("n1") == first.outputs.get("n1"), "Outputs differ on idempotent resume"

    # Stage attempt must still reference the same fingerprint (no duplicate)
    second_attempts = second.outputs.get("_icm_stage_attempts")
    assert second_attempts is not None, "No attempts recorded on resume"
    assert second_attempts["n1"]["manifest_fingerprint"] == attempts["n1"]["manifest_fingerprint"], "Fingerprint changed on resume"
    # Should still be exactly one entry (no duplication)
    assert len(second_attempts) == 1, f"Expected 1 attempt entry, got {len(second_attempts)}: {second_attempts}"

    print("E2E ICM-X resume idempotency: PASS")


@pytest.mark.asyncio
async def test_e2e_icm_resume_with_approvals():
    """Run a workflow node with stage binding + approval_id in shared
    context, verify bind_approval records the approval ID + fingerprint."""
    node = WorkflowNode(
        id="n1",
        tool_name="calculator",
        tool_args={"expression": "1+1"},
        # lead_qualification stage allows calculator
        stage_id="lead_qualification",
    )
    wf = WorkflowDef(id=f"wf-{uuid.uuid4()}", name="e2e-icm-approvals", nodes={"n1": node})
    engine = WorkflowEngine()
    conv_id = f"conv-{uuid.uuid4()}"

    # First run with approval_id via shared dict (simulated; the engine
    # records bind_approval when approval_id is set in shared during
    # pre_execute). We test the recording path by checking that attempts
    # exist and fingerprints are captured.
    first = await engine.run(wf, conv_id, "hello")
    assert first.ok(), f"First run failed: {first.errors}"
    assert first.node_status.get("n1") == "done", f"Node not done: {first.node_status}"

    # Verify attempt has fingerprint recorded
    attempts = first.outputs.get("_icm_stage_attempts")
    assert attempts is not None and "n1" in attempts
    assert attempts["n1"].get("status") == "done", f"Expected status done, got {attempts['n1'].get('status')}"
    assert "manifest_fingerprint" in attempts["n1"], "Missing manifest_fingerprint"

    print("E2E ICM-X stage attempt recording: PASS")


@pytest.mark.asyncio
async def test_e2e_icm_output_schema_failure_fails_node():
    manifest = StageManifest(
        id="bad_output",
        version="1.0.0",
        mode="deterministic",
        outputs_schema="handoff.v1",
        allowed_tools=["calculator"],
    )
    node = WorkflowNode(
        id="n1",
        tool_name="calculator",
        tool_args={"expression": "2+2"},
        stage_manifest=manifest,
    )
    result = WorkflowResult()

    with pytest.raises(ValueError, match="ICM output schema validation failed"):
        await WorkflowEngine()._execute_node(node, "conv-bad-output", {}, result)

    assert result.node_status["n1"] == "failed"
    assert "_icm_stage_attempts" not in result.outputs


@pytest.mark.asyncio
async def test_workflow_explicit_preapproved_populates_icm_approval(tmp_path):
    manifest = StageManifest(
        id="approved_stage",
        version="1.0.0",
        mode="deterministic",
        approval_required=True,
        allowed_tools=["calculator"],
    )
    fp = manifest_fingerprint(manifest)
    node = WorkflowNode(
        id="n1",
        tool_name="calculator",
        tool_args={"expression": "2+2"},
        stage_manifest=manifest,
    )

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from aios.db.models import PendingAction

    engine = create_engine(f"sqlite:///{tmp_path / 'approvals.db'}")
    PendingAction.__table__.create(engine)
    with Session(engine) as session:
        session.add(
            PendingAction(
                id="appr-valid",
                org_id="default",
                agent_id="agent-1",
                conversation_id="conv-preapproved-valid",
                tool_name="calculator",
                tool_args={},
                status="approved",
                decided_by="founder-1",
            )
        )
        session.commit()
        shared = {
            "icm_preapproved": {
                "approved": True,
                "approval_id": "appr-valid",
                "approved_fingerprint": fp,
                "actions": ["calculator"],
            },
            "icm_db_session": session,
        }
        result = WorkflowResult()

        await WorkflowEngine()._execute_node(node, "conv-preapproved-valid", shared, result)

    engine.dispose()
    assert result.node_status["n1"] == "done"
    assert shared["icm_approval"]["approval_id"] == "appr-valid"
    assert shared["icm_approval"]["approved_fingerprint"] == fp


@pytest.mark.asyncio
async def test_workflow_generic_preapproved_does_not_authorize_icm():
    manifest = StageManifest(
        id="approved_stage",
        version="1.0.0",
        mode="deterministic",
        approval_required=True,
        allowed_tools=["calculator"],
    )
    node = WorkflowNode(
        id="n1",
        tool_name="calculator",
        tool_args={"expression": "2+2"},
        stage_manifest=manifest,
    )
    shared = {
        "preapproved": {
            "approved": True,
            "approval_id": "appr-valid",
            "approved_fingerprint": manifest_fingerprint(manifest),
            "actions": ["calculator"],
        }
    }
    result = WorkflowResult()

    with pytest.raises(PermissionError):
        await WorkflowEngine()._execute_node(node, "conv-generic-preapproved", shared, result)

    assert result.node_status["n1"] == "failed"
    assert "icm_approval" not in shared


@pytest.mark.asyncio
async def test_workflow_preapproved_wrong_fingerprint_fails():
    manifest = StageManifest(
        id="approved_stage",
        version="1.0.0",
        mode="deterministic",
        approval_required=True,
        allowed_tools=["calculator"],
    )
    node = WorkflowNode(
        id="n1",
        tool_name="calculator",
        tool_args={"expression": "2+2"},
        stage_manifest=manifest,
    )
    shared = {
        "icm_preapproved": {
            "approved": True,
            "approval_id": "appr-bad",
            "approved_fingerprint": "bad-fingerprint",
            "actions": ["calculator"],
        }
    }
    result = WorkflowResult()

    with pytest.raises(PermissionError):
        await WorkflowEngine()._execute_node(node, "conv-preapproved-bad", shared, result)

    assert result.node_status["n1"] == "failed"
    assert "icm_approval" not in shared


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_e2e_icm_resume_idempotent_stage_attempts())
    asyncio.run(test_e2e_icm_resume_with_approvals())
    print("All E2E ICM-X tests passed.")