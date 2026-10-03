"""Orchestrator regressions: routing that silently reached the wrong agent.

These assert on what `_llm_route` is shown and what it returns, not on the
whole routing path: the route body opens a DB session for the blackboard and
telemetry, which is not what these defects are about.
"""

import hashlib

import pytest

from aios.core.orchestrator import TeamOrchestrator, _json_from_text


class _A:
    def __init__(self, i):
        self.id = f"a{i}"
        self.name = f"Agent{i}"
        self.agent_type = "custom"
        self.system_prompt = f"prompt {i}"
        self.org_id = "o"
        self.governance_config = {}


class _Team:
    routing_strategy = "supervisor"
    orchestrator_agent_id = None
    manager_agent_id = None


def _shard(conv_id: str, n: int) -> list:
    """Mirror of the >=8-agent shard selection in _supervisor_route."""
    h = int(hashlib.md5(conv_id.encode()).hexdigest(), 16) % 4
    return [a for i, a in enumerate([_A(i) for i in range(n)]) if i % 4 == h]


# ─── supervisor sharding remapped the LLM's choice onto the wrong agent ────

@pytest.mark.asyncio
async def test_llm_route_enumerates_the_pool_it_was_given(monkeypatch):
    """The index _llm_route returns indexes whatever list it enumerated. A
    sharded caller used to enumerate the full team and apply the index to the
    shard, remapping the supervisor's pick onto a different agent."""
    team = [_A(i) for i in range(8)]
    orch = TeamOrchestrator(_Team(), team)
    shard = [a for i, a in enumerate(team) if i % 4 == 1]

    shown = {}

    async def _fake_chat(messages, **kw):
        system = messages[0]["content"]
        shown["lines"] = [ln for ln in system.splitlines() if ln.startswith("[")]
        return {"tool_calls": [{"function": {"name": "_route",
                        "arguments": '{"agent_index": 1, "reason": "r", "handoff_message": "m"}'}}]}

    import aios.core.orchestrator as O

    class _P:
        def chat_retry(self, messages, **kw):
            return _fake_chat(messages, **kw)

    monkeypatch.setattr(O, "get_provider", lambda *a, **k: _P())

    async def _shared(_c):
        return ""

    monkeypatch.setattr(orch, "_shared_context_for", _shared)

    routed = await orch._llm_route("msg", "conv", candidates=shard)

    assert routed["agent_index"] == 1
    assert len(shown["lines"]) == len(shard), (
        f"route saw {len(shown['lines'])} candidates, expected the {len(shard)}-member shard"
    )
    # index 1 of the shown list is the agent the caller will actually use
    assert shard[1].name in shown["lines"][1]


@pytest.mark.asyncio
async def test_llm_route_defaults_to_the_whole_team(monkeypatch):
    team = [_A(i) for i in range(3)]
    orch = TeamOrchestrator(_Team(), team)
    shown = {}

    async def _fake_chat(messages, **kw):
        shown["lines"] = [ln for ln in messages[0]["content"].splitlines() if ln.startswith("[")]
        return {"tool_calls": [{"function": {"name": "_route",
                        "arguments": '{"agent_index": 2, "reason": "r", "handoff_message": "m"}'}}]}

    import aios.core.orchestrator as O

    class _P:
        def chat_retry(self, messages, **kw):
            return _fake_chat(messages, **kw)

    monkeypatch.setattr(O, "get_provider", lambda *a, **k: _P())
    monkeypatch.setattr(orch, "_shared_context_for", lambda c: _empty())

    routed = await orch._llm_route("msg", "conv")
    assert routed["agent_index"] == 2 and len(shown["lines"]) == 3


async def _empty():
    return ""


# ─── manager JSON wrapped in prose discarded the whole plan ────────────────

def test_json_from_text_handles_prose_and_fences():
    assert _json_from_text('{"assignments": [{"agent_id": "a1"}]}')["assignments"]
    fenced = 'Aqui está o plano:\n```json\n{"assignments": [{"agent_id": "a2"}]}\n```\nFim.'
    assert _json_from_text(fenced)["assignments"][0]["agent_id"] == "a2"
    inline = 'Plan approved. {"assignments": []} - that is my decision.'
    assert _json_from_text(inline) == {"assignments": []}


def test_json_from_text_returns_none_when_there_is_no_json():
    assert _json_from_text("no json here at all") is None
    assert _json_from_text("") is None


# ─── streaming broadcast skipped the judge ────────────────────────────────

@pytest.mark.asyncio
async def test_broadcast_stream_uses_the_same_judge(monkeypatch):
    """Streaming returned max(len) while non-streaming ran the judge, so the
    same team answered differently depending on the caller's path."""
    orch = TeamOrchestrator(_Team(), [_A(i) for i in range(3)])

    async def _fake_pick(valid):
        return "JUDGED"

    monkeypatch.setattr(orch, "_pick_best_answer", _fake_pick)

    class _RT:
        async def run(self, conv_id, msg, db=None):
            return "  short  "

    monkeypatch.setattr("aios.core.orchestrator._get_runtime", lambda a, db=None: _RT())

    out = []
    async for ev in orch._broadcast_stream("c", "m"):
        if ev["type"] == "token":
            out.append(ev["content"])
    assert "JUDGED" in "".join(out), "streaming broadcast did not run the judge"