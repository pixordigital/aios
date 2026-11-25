"""Detached autonomous HITL verdict resume — bounded, org-scoped, one-shot.

No DB/LLM here. The handler must resume only on a real approval, keep the org
and conversation, and leave side-effect gating to AgentRuntime.
"""

from contextlib import asynccontextmanager

import pytest

from aios.db.models import PendingAction


@pytest.fixture(autouse=True)
async def _fresh_db():
    """Shadow conftest's autouse drop_all/create_all; these fakes need no DB."""
    yield


class _Agent:
    id = "a-hitl"
    org_id = "org-1"
    name = "Auto"
    system_prompt = "p"
    llm_config = {}
    tools = []
    governance_config = {"autonomous": True, "hitl_enabled": True, "max_trials": 1}
    extra_data: dict = {}


class _Conv:
    def __init__(self, org_id="org-1", extra=None):
        self.id = "conv-1"
        self.org_id = org_id
        self.extra_data = {} if extra is None else extra


class _ApprovalRow:
    def __init__(self, action_id, org_id="org-1", status="approved",
                 decided_by="human-1", tool_name="autonomous_hitl", tool_args=None):
        self.id = action_id
        self.org_id = org_id
        self.status = status
        self.decided_by = decided_by
        self.tool_name = tool_name
        self.tool_args = {} if tool_args is None else tool_args


class _DB:
    def __init__(self, conv, approval=None):
        self.conv = conv
        self.approval = approval
        self.commits = 0

    async def get(self, model, ident, **kwargs):
        if model is PendingAction:
            if self.approval is None or ident != self.approval.id:
                return None
            return self.approval
        assert ident == self.conv.id
        if "with_for_update" in kwargs:
            assert kwargs["with_for_update"] is True
        return self.conv

    async def commit(self):
        self.commits += 1


class _Runtime:
    def __init__(self):
        self.calls = []

    async def run(self, conv_id, message, db=None, approved_hitl=None):
        # No _hitl_tool_reason / tool_engine here on purpose: the handler may
        # not duplicate AgentRuntime's pre-execution gate.
        self.calls.append((conv_id, message, db, approved_hitl))


def _harness(monkeypatch, conv, approval=None):
    from aios.core.autonomous_agent import AutonomousAgent
    from aios.db import backend as db_backend

    auto = AutonomousAgent(_Agent())
    auto.runtime = _Runtime()
    backend_db = _DB(conv, approval)

    @asynccontextmanager
    async def _session():
        yield backend_db

    monkeypatch.setattr(db_backend, "db_session", _session)
    return auto, backend_db


def _verdict(monkeypatch, approved, seen):
    from aios.core.approval import approval_manager

    async def _decide(**kwargs):
        seen.update(kwargs)
        return approved

    monkeypatch.setattr(approval_manager, "request_approval", _decide)


@pytest.mark.asyncio
async def test_approval_resumes_once_in_org_and_conversation(monkeypatch):
    args = {
        "user_message": "do the thing",
        "response": "approval needed",
        "reason": "high value",
    }
    row = _ApprovalRow("act-1", tool_args=args)
    auto, backend_db = _harness(monkeypatch, _Conv(extra={"keep": "yes"}), row)
    seen = {}
    _verdict(monkeypatch, True, seen)
    hitl_calls = []

    async def _no_second_hitl(*a, **kw):
        hitl_calls.append((a, kw))
        return "act-unexpected"

    auto._create_hitl = _no_second_hitl

    await auto._await_hitl_decision(
        "act-1", "conv-1", "do the thing", "approval needed", "high value"
    )

    assert seen["org_id"] == "org-1"
    assert seen["conversation_id"] == "conv-1"
    assert seen["tool_name"] == "autonomous_hitl"
    assert seen["tool_args"] == args
    assert len(auto.runtime.calls) == 1
    conv_id, message, db, marker = auto.runtime.calls[0]
    assert (conv_id, message) == ("conv-1", "do the thing")
    assert db is backend_db
    assert marker == {
        "action_id": "act-1",
        "tool_name": "autonomous_hitl",
        "tool_args": args,
    }
    assert hitl_calls == []  # no chained HITL for the same action
    assert backend_db.commits == 1
    assert backend_db.conv.extra_data == {
        "keep": "yes",
        "autonomous_hitl_resumed": ["act-1"],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("row", [
    None,
    _ApprovalRow("act-5", status="pending"),
    _ApprovalRow("act-5", org_id="org-2"),
    _ApprovalRow("act-5", decided_by=None),
])
async def test_no_valid_approved_row_does_not_resume(monkeypatch, row):
    auto, backend_db = _harness(monkeypatch, _Conv(), row)
    seen = {}
    _verdict(monkeypatch, True, seen)

    await auto._await_hitl_decision(
        "act-5", "conv-1", "do the thing", "approval needed", "high value"
    )

    assert auto.runtime.calls == []
    assert backend_db.commits == 0
    assert "autonomous_hitl_resumed" not in backend_db.conv.extra_data


@pytest.mark.asyncio
async def test_reject_or_timeout_does_not_resume(monkeypatch):
    # request_approval returns False for both reject and timeout.
    auto, backend_db = _harness(monkeypatch, _Conv())
    seen = {}
    _verdict(monkeypatch, False, seen)

    await auto._await_hitl_decision(
        "act-2", "conv-1", "do the thing", "approval needed", "high value"
    )

    assert auto.runtime.calls == []
    assert backend_db.commits == 0
    assert "autonomous_hitl_resumed" not in backend_db.conv.extra_data


@pytest.mark.asyncio
async def test_repeated_verdict_cannot_resume_twice(monkeypatch):
    auto, backend_db = _harness(monkeypatch, _Conv(), _ApprovalRow("act-3"))
    seen = {}
    _verdict(monkeypatch, True, seen)

    for _ in range(2):
        await auto._await_hitl_decision(
            "act-3", "conv-1", "do the thing", "approval needed", "high value"
        )

    assert len(auto.runtime.calls) == 1
    assert backend_db.commits == 1
    assert backend_db.conv.extra_data["autonomous_hitl_resumed"] == ["act-3"]


@pytest.mark.asyncio
async def test_cross_org_conversation_is_not_resumed(monkeypatch):
    auto, backend_db = _harness(monkeypatch, _Conv(org_id="org-2"))
    seen = {}
    _verdict(monkeypatch, True, seen)

    await auto._await_hitl_decision(
        "act-4", "conv-1", "do the thing", "approval needed", "high value"
    )

    assert auto.runtime.calls == []
    assert backend_db.commits == 0
    assert "autonomous_hitl_resumed" not in backend_db.conv.extra_data


class _HitlRuntime:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def run_stream(self, conv_id, message, db=None):
        self.calls.append((conv_id, message, db))
        yield {"type": "token", "content": self.response}


@pytest.mark.asyncio
async def test_non_resumed_run_still_creates_hitl():
    from aios.core.autonomous_agent import AutonomousAgent

    auto = AutonomousAgent(_Agent())
    auto.runtime = _HitlRuntime("Vou criar proposta de R$ 10.000 para o deal")
    hitl_calls = []

    async def _record_hitl(conv_id, user_message, response, db, reason="Valor > threshold"):
        hitl_calls.append((conv_id, user_message, response, db, reason))
        return "act-new"

    auto._create_hitl = _record_hitl

    result = await auto.run("conv-1", "Crie uma proposta de R$ 10.000 para o deal")

    assert result.startswith("⏸️ [HITL]")
    assert "act-new" in result
    assert len(hitl_calls) == 1
    assert hitl_calls[0][0] == "conv-1"
    assert "10.000" in hitl_calls[0][2]
