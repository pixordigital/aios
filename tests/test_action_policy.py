import json

import pytest

from aios.core.action_policy import ActionClass, classify_tool_action, requires_human_approval
from aios.core.tools import ToolEngine, ToolExecutionError
from aios.tools.registry import TOOL_REGISTRY


def test_read_only_tool_allowed():
    d = classify_tool_action("rag_search", {"query": "hi"})
    assert d.action_class == ActionClass.READ_INTERNAL
    assert d.requires_approval is False


def test_unknown_tool_fail_closed():
    d = classify_tool_action("totally_unknown_tool", {"x": 1})
    assert d.action_class == ActionClass.UNKNOWN_SIDE_EFFECT
    assert d.requires_approval is True
    assert d.fail_closed is True


def test_dynamic_tool_requires_approval(monkeypatch):
    TOOL_REGISTRY["dyn_test_policy"] = {
        "code_reference": "aios.tools.dynamic.dyn_test_policy",
        "dynamic": True,
    }
    try:
        d = classify_tool_action("dyn_test_policy", {"a": 1})
        assert d.requires_approval is True
        assert d.action_class == ActionClass.UNKNOWN_SIDE_EFFECT
    finally:
        TOOL_REGISTRY.pop("dyn_test_policy", None)


def test_destructive_sql_requires_approval():
    d = classify_tool_action("sql_query", {"query": "DELETE FROM agents"})
    assert d.action_class == ActionClass.DESTRUCTIVE
    assert d.requires_approval is True


def test_bulk_email_requires_approval():
    d = classify_tool_action("send_email", {"to": [f"a{i}@x.com" for i in range(100)], "subject": "s", "body": "b"})
    assert d.action_class == ActionClass.BULK_COMMS
    assert d.requires_approval is True


@pytest.mark.asyncio
async def test_tool_engine_fail_closed_unknown_tool():
    # Register fake unknown tool entry? easier: bypass missing by putting in tools dict not needed; execute checks registry.
    # Use a name in tools but not in registry by direct dict injection.
    eng = ToolEngine([], org_id="o1", agent_id="a1")
    class _T:
        async def run(self, **kwargs):
            return {"ok": True}
    eng.tools["ghost_tool"] = _T()
    TOOL_REGISTRY["ghost_tool"] = {"code_reference": "aios.tools.base.BaseTool"}  # not in allowed modules
    try:
        with pytest.raises(ToolExecutionError):
            await eng.execute("ghost_tool", json.dumps({}))
    finally:
        TOOL_REGISTRY.pop("ghost_tool", None)


@pytest.mark.asyncio
async def test_tool_engine_blocks_risky_without_approval():
    eng = ToolEngine(["send_email"], org_id="o1", agent_id="a1")
    with pytest.raises(ToolExecutionError) as exc:
        await eng.execute("send_email", json.dumps({"to": "a@b.com", "subject": "s", "body": "b"}))
    assert "HITL/action policy" in str(exc.value)


@pytest.mark.asyncio
async def test_tool_engine_allows_read_only_without_approval():
    eng = ToolEngine(["current_datetime"], org_id="o1", agent_id="a1")
    out = await eng.execute("current_datetime", json.dumps({}))
    data = json.loads(out)
    assert "utc" in data
