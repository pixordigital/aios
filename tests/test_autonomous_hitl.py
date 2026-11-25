"""Detached autonomous HITL verdict resume — bounded, org-scoped, one-shot.

No DB/LLM here. The handler must resume only on a real approval, keep the org
and conversation, and leave side-effect gating to AgentRuntime.
"""

from contextlib import asynccontextmanager

import pytest


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


class _DB:
    def __init__(self, conv):
        self.conv = conv
        self.commits = 0

    async def get(self, model, ident, **kwargs):
        assert ident == self.conv.id
        assert kwargs["with_for_update"] is True
        return self.conv

    async def commit(self):
        self.commits += 1


class _Runtime:
    def __init__(self):
        self.calls = []

    async def run(self, conv_id, message, db=None):
        # No _hitl_tool_reason / tool_engine here on purpose: the handler may
        # not duplicate AgentRuntime's pre-execution gate.
        self.calls.append((conv_id, message, db))


def _harness(monkeypatch, conv):
    from aios.core.autonomous_agent import AutonomousAgent
    from aios.db import backend as db_backend

    auto = AutonomousAgent(_Agent())
    auto.runtime = _Runtime()
    backend_db = _DB(conv)

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
    auto, backend_db = _harness(monkeypatch, _Conv(extra={"keep": "yes"}))
    seen = {}
    _verdict(monkeypatch, True, seen)

    await auto._await_hitl_decision(
        "act-1", "conv-1", "do the thing", "approval needed", "high value"
    )

    assert seen["org_id"] == "org-1"
    assert seen["conversation_id"] == "conv-1"
    assert seen["tool_name"] == "autonomous_hitl"
    assert len(auto.runtime.calls) == 1
    conv_id, message, db = auto.runtime.calls[0]
    assert (conv_id, message) == ("conv-1", "do the thing")
    assert db is backend_db
    assert backend_db.commits == 1
    assert backend_db.conv.extra_data == {
        "keep": "yes",
        "autonomous_hitl_resumed": ["act-1"],
    }


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
    auto, backend_db = _harness(monkeypatch, _Conv())
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
