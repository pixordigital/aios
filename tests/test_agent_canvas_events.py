"""Agent canvas event bridge — self-contained regression checks.

These deliberately avoid the shared conftest DB fixtures: the repo's test suite
uses a function-scoped autouse drop_all/create_all against one shared file
SQLite, which is slow and racy when anything else touches it concurrently.
Nothing here needs a database — the org filter, event tagging and trial events
are all pure in-process logic, so they can be asserted directly and fast.

The cases that matter:
  * the tenant filter rejects a mismatched org and keeps a matching one (T5)
  * events carry agent_id/org_id/run_id, or the canvas cannot place a node
  * an autonomous trial publishes its boundary event
"""

import pytest

from aios.core import agent_events
from aios.core.hooks import HookContext, HookPoint, hooks
from aios.core.ws_manager import WSManager


@pytest.fixture(autouse=True)
async def _fresh_db():
    """Shadow conftest's autouse DB reset — nothing here touches a database.

    Without this these tests inherit a function-scoped drop_all/create_all
    against the shared file SQLite, which is slow, racy under concurrency, and
    entirely unnecessary for pure in-process event logic.
    """
    yield


class FakeWS:
    """Records what the manager pushed, and can be told to fail like a dead socket."""

    def __init__(self, fail: bool = False):
        self.sent: list[dict] = []
        self.fail = fail

    async def send_json(self, data):
        if self.fail:
            raise RuntimeError("socket closed")
        self.sent.append(data)


class FakeAgent:
    def __init__(self, aid="a-1", org="org-1"):
        self.id = aid
        self.org_id = org
        self.name = "Agent One"


# ── tenant isolation ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deliver_drops_event_for_other_org():
    """T5: an event must never reach another tenant's canvas."""
    m = WSManager()
    mine = FakeWS()
    theirs = FakeWS()
    m.register(mine, "org-1")
    m.register(theirs, "org-2")

    await m._deliver_local({"type": "token", "org_id": "org-1", "content": "secret"})

    assert len(mine.sent) == 1, "matching org should receive the event"
    assert theirs.sent == [], "cross-tenant event leaked to org-2"


@pytest.mark.asyncio
async def test_deliver_without_org_id_reaches_no_clients():
    """Org-less events are dropped, not broadcast.

    This used to assert the opposite ("reaches_all_clients") and document the
    blanket fan-out as intended legacy behaviour. It was a cross-tenant leak:
    every emitter degrades org_id to "" when the agent or hook context carries
    none, and clients always register with a real user.org_id, so those events
    reached every connected tenant. Delivery now fails closed.
    """
    m = WSManager()
    a, b = FakeWS(), FakeWS()
    m.register(a, "org-1")
    m.register(b, "org-2")

    await m._deliver_local({"type": "approval_requested", "action_id": "x"})
    await m._deliver_local({"type": "approval_requested", "action_id": "x", "org_id": ""})

    assert a.sent == [], "org-less event must not be broadcast"
    assert b.sent == [], "org-less event must not be broadcast"


@pytest.mark.asyncio
async def test_approval_requested_is_org_scoped():
    """approval.py now supplies org_id, so the approval fan-out still works."""
    m = WSManager()
    a, b = FakeWS(), FakeWS()
    m.register(a, "org-1")
    m.register(b, "org-2")

    await m._deliver_local({"type": "approval_requested", "action_id": "x", "org_id": "org-1"})

    assert len(a.sent) == 1
    assert b.sent == []


@pytest.mark.asyncio
async def test_dead_socket_is_evicted():
    m = WSManager()
    dead = FakeWS(fail=True)
    m.register(dead, "org-1")
    assert m.client_count == 1

    await m._deliver_local({"type": "token", "org_id": "org-1"})

    assert m.client_count == 0, "a socket that failed to send should be dropped"


@pytest.mark.asyncio
async def test_broadcast_is_sync_safe_and_bounded():
    """broadcast() is called from the synchronous hook registry."""
    from aios.core.ws_manager import MAX_QUEUE

    m = WSManager()
    m.broadcast({"type": "token", "org_id": "org-1"})  # must not need await
    assert m.queue.qsize() == 1

    for _ in range(MAX_QUEUE + 50):
        m.broadcast({"type": "token", "org_id": "org-1"})
    assert m.queue.qsize() == MAX_QUEUE, "queue must not grow past its bound"


# ── event tagging ─────────────────────────────────────────────────


def test_stream_event_carries_agent_identity():
    """Without these the canvas gets an anonymous firehose and cannot draw nodes."""
    ev = agent_events.emit_stream_event(
        FakeAgent(), {"type": "token", "content": "hi"}, "run-9"
    )
    assert ev["agent_id"] == "a-1"
    assert ev["org_id"] == "org-1"
    assert ev["run_id"] == "run-9"
    assert ev["content"] == "hi", "original payload must survive tagging"


def test_stream_event_does_not_mutate_caller_dict():
    original = {"type": "token", "content": "hi"}
    agent_events.emit_stream_event(FakeAgent(), original, "run-9")
    assert "agent_id" not in original, "tagging must not leak into the yielded dict"


def test_trial_event_shape():
    ev = agent_events.emit_trial_event(FakeAgent(), 2, 3, "conv-7")
    assert ev["type"] == "trial_start"
    assert (ev["trial"], ev["max_trials"]) == (2, 3)
    assert ev["org_id"] == "org-1"


@pytest.mark.asyncio
async def test_lifecycle_hooks_publish_org_scoped_events():
    """The canvas relies on hooks for node state; org must ride along."""
    from aios.core.ws_manager import WSManager as _M

    isolated = _M()
    # The handlers resolve `ws_manager` in agent_events' own globals, not via
    # the ws_manager module attribute, so patch it there.
    saved = agent_events.ws_manager
    agent_events.ws_manager = isolated
    try:
        for handler in (
            agent_events._on_agent_start,
            agent_events._on_agent_end,
            agent_events._on_agent_error,
        ):
            handler(
                HookContext(
                    agent_id="a-1",
                    org_id="org-1",
                    conversation_id="c-1",
                    data={"error": "boom"},
                )
            )
    finally:
        agent_events.ws_manager = saved

    captured = []
    while not isolated.queue.empty():
        captured.append(isolated.queue.get_nowait())

    assert [e["type"] for e in captured] == [
        "node_start",
        "node_end",
        "node_error",
    ]
    for e in captured:
        assert e["agent_id"] == "a-1"
        assert e["org_id"] == "org-1", "lifecycle events must be tenant-scoped"
    assert captured[-1]["error"] == "boom"


def test_register_hooks_is_idempotent_per_process():
    """lifespan must be safe to re-enter (reload, test client, restart).

    A second registration would publish every lifecycle event twice, so the
    canvas would show duplicate start/end flashes.
    """
    from aios.core.hooks import HookRegistry

    reg = HookRegistry()
    saved_hooks, saved_flag = hooks._hooks, agent_events._hooks_registered
    hooks._hooks, agent_events._hooks_registered = reg._hooks, False
    try:
        agent_events.register_hooks()
        agent_events.register_hooks()
        assert len(reg._hooks[HookPoint.AGENT_START]) == 1
        assert len(reg._hooks[HookPoint.AGENT_END]) == 1
        assert len(reg._hooks[HookPoint.AGENT_ERROR]) == 1
    finally:
        hooks._hooks = saved_hooks
        agent_events._hooks_registered = saved_flag


# ── autonomous streaming (T2) ──────────────────────────────────────


class _FakeRuntime:
    """Stands in for AgentRuntime inside AutonomousAgent."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = 0

    async def run_stream(self, conv_id, message, db=None):
        self.calls += 1
        for c in self.chunks:
            yield {"type": "token", "content": c}
        yield {"type": "done"}


class _StubAgent:
    id = "a-auto"
    org_id = "org-1"
    name = "Auto"
    system_prompt = "p"
    llm_config = {}
    tools = []
    governance_config = {"autonomous": True, "max_trials": 2,
                         "hitl_enabled": False}


@pytest.mark.asyncio
async def test_autonomous_run_stream_emits_trial_and_tokens(monkeypatch):
    """T2: autonomous agents must stream, including trial boundaries.

    _get_runtime() returns AutonomousAgent for autonomous agents, but the class
    had no run_stream, so the orchestrator's streaming paths could not use it
    and those agents stayed dark on the canvas.
    """
    from aios.core.autonomous_agent import AutonomousAgent

    auto = AutonomousAgent(_StubAgent())
    auto.max_trials = 1
    auto.runtime = _FakeRuntime(["hello ", "world"])
    # Skip the evaluator/reflection machinery: this test is about the streaming
    # plumbing, not the scoring heuristics.
    auto.evaluator = type(
        "E", (), {"evaluate": lambda self, *a, **k: {"success": True, "reason": "ok", "confidence": 1}}
    )()

    isolated = WSManager()
    saved = agent_events.ws_manager
    agent_events.ws_manager = isolated
    try:
        events = [e async for e in auto.run_stream("conv-1", "do it")]
    finally:
        agent_events.ws_manager = saved

    kinds = [e.get("type") for e in events]
    assert "trial_start" in kinds, f"no trial boundary in {kinds}"
    assert "token" in kinds, f"no tokens streamed in {kinds}"
    trial = next(e for e in events if e["type"] == "trial_start")
    assert trial["agent_id"] == "a-auto"
    assert trial["org_id"] == "org-1"
    text = "".join(e.get("content", "") for e in events if e.get("type") == "token")
    assert text == "hello world", f"streamed text mismatch: {text!r}"


# ── hierarchical handoff (the :647 fix) ───────────────────────────


class _StubTeam:
    id = "t-1"
    name = "Sales"
    org_id = "org-1"
    routing_strategy = "hierarchical"
    handoff_config: dict = {}
    orchestrator_agent_id = "a-orch"
    manager_agent_id = "a-mgr"
    extra_data: dict = {}


def _stub_agent(aid, name):
    class S:
        pass

    s = S()
    s.id, s.name, s.org_id = aid, name, "org-1"
    s.governance_config = {"autonomous": False}
    # Both are read while building the manager prompt and the routing prompt.
    # Real Agent rows always have them (column defaults), so a stub without
    # them raised AttributeError and the stream never reached the delegation.
    s.agent_type = "custom"
    s.system_prompt = ""
    return s


@pytest.mark.asyncio
async def test_hierarchical_stream_emits_handoff_and_runs_the_runtime(monkeypatch):
    """Regression: the hierarchical path called run_stream on the raw ORM Agent.

    `agent` there is a DB model with no run_stream, so the AttributeError was
    swallowed by a bare `except` and every hierarchical stream silently fell
    through to the supervisor fallback. The manager's delegations never ran.
    """
    import json as _json

    from aios.core import orchestrator as orch

    orch_a = _stub_agent("a-orch", "Orchestrator")
    mgr = _stub_agent("a-mgr", "Manager")
    worker = _stub_agent("a-1", "Worker")

    # All three tiers must be present: the method bails to the supervisor
    # fallback when the orchestrator or manager is not in the team.
    team = _StubTeam()
    team.agents = [orch_a, mgr, worker]

    to = orch.TeamOrchestrator(team, [orch_a, mgr, worker])

    ran: list[tuple] = []

    class _RT:
        def __init__(self, agent, db=None):
            self.agent = agent

        async def run(self, conv_id, prompt, db=None):
            ran.append((self.agent.id, prompt))
            if self.agent.id == "a-orch":
                return "plan: manager should route to closing"
            if self.agent.id == "a-mgr":
                return _json.dumps({
                    "assignments": [
                        {"agent_id": "a-1", "task": "call the lead",
                         "reason": "owns closing"}
                    ],
                    "manager_notes": "",
                })
            return "ok"

        async def run_stream(self, conv_id, msg, db=None):
            ran.append((self.agent.id, msg))
            yield {"type": "token", "content": "done"}

    monkeypatch.setattr(orch, "_get_runtime", lambda a, db=None: _RT(a, db))

    events = [e async for e in to._hierarchical_route_stream("c-1", "help", None)]
    kinds = [e.get("type") for e in events]

    assert "handoff" in kinds, f"no structured handoff emitted: {kinds}"
    assert not any(k == "supervisor_fallback" for k in kinds)

    handoff = next(e for e in events if e["type"] == "handoff")
    assert handoff["from_agent_id"] == "a-mgr"
    assert handoff["to_agent_id"] == "a-1"
    assert handoff["org_id"] == "org-1"
    assert handoff["task"] == "call the lead"

    # The worker must actually have been run through the runtime.
    assert ("a-1", "call the lead") in ran, f"worker never executed: {ran}"
    # ...and its tokens must reach the stream.
    assert any(e.get("content") == "done" for e in events)
