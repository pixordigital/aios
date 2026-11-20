import uuid

import pytest

from aios.core.workflow import WorkflowDef, WorkflowEngine, WorkflowNode


@pytest.mark.asyncio
async def test_workflow_resume_idempotent_stage_attempts():
    node = WorkflowNode(id="n1", tool_name="calculator", tool_args={"expression": "2+2"})
    wf = WorkflowDef(id=f"wf-{uuid.uuid4()}", name="resume-icm", nodes={"n1": node})
    engine = WorkflowEngine()
    conv_id = f"conv-{uuid.uuid4()}"
    first = await engine.run(wf, conv_id, "hello")
    assert first.ok()
    assert first.node_status.get("n1") == "done"

    second = await engine.run(
        wf,
        conv_id,
        "hello",
        resume_outputs=dict(first.outputs),
        resume_status=dict(first.node_status),
    )
    assert second.ok()
    assert second.node_status.get("n1") == "done"
    assert second.outputs.get("n1") == first.outputs.get("n1")