"""Workflow runs must emit deterministic process-conformance findings."""

import json
import uuid

from aios.core.workflow import WorkflowDef, WorkflowEngine, WorkflowNode
from aios.icm.contracts import StageManifest


def _conformance(result):
    return json.loads(result.outputs["_process_conformance"])


async def test_skipped_step_is_reported():
    skipped = WorkflowNode(
        id="n1", tool_name="calculator", tool_args={"expression": "2+2"},
        condition="False",
    )
    done = WorkflowNode(
        id="n2", tool_name="calculator", tool_args={"expression": "3+3"},
        depends_on=["n1"],
    )
    wf = WorkflowDef(id=f"wf-{uuid.uuid4()}", name="conformance", nodes={"n1": skipped, "n2": done})

    result = await WorkflowEngine().run(wf, f"conv-{uuid.uuid4()}", "hello")

    assert result.ok(), result.errors
    report = _conformance(result)
    assert report["deviation"] == "execution_deviation"
    assert any("skipped steps" in f for f in report["findings"])


async def test_missing_stage_approval_blocks_execution():
    manifest = StageManifest(
        id="approval-stage", version="1.0.0", mode="deterministic",
        approval_required=True, allowed_tools=["calculator"],
    )
    node = WorkflowNode(
        id="n1", tool_name="calculator", tool_args={"expression": "2+2"},
        stage_manifest=manifest,
    )
    wf = WorkflowDef(id=f"wf-{uuid.uuid4()}", name="conformance-approval", nodes={"n1": node})

    result = await WorkflowEngine().run(wf, f"conv-{uuid.uuid4()}", "hello")

    assert not result.ok()
    assert "requires approval" in result.errors["n1"]
    assert result.node_status["n1"] == "failed"
    assert "n1" not in result.outputs


async def test_side_effects_count_as_approval_required():
    manifest = StageManifest(
        id="side-effect-stage", version="1.0.0", mode="deterministic",
        side_effects=True, allowed_tools=["calculator"],
    )
    node = WorkflowNode(
        id="n1", tool_name="calculator", tool_args={"expression": "2+2"},
        stage_manifest=manifest,
    )
    wf = WorkflowDef(id=f"wf-{uuid.uuid4()}", name="conformance-side-effects", nodes={"n1": node})

    result = await WorkflowEngine().run(wf, f"conv-{uuid.uuid4()}", "hello")

    assert not result.ok()
    assert any("missing approval" in f for f in _conformance(result)["findings"])
