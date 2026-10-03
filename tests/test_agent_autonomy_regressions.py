"""Regressions that kept autonomous agents from completing their work.

Each test pins one defect that made a customer's agent fail or degrade. They
are deliberately behavioural — a source-grep test would pass while the bug
returned.
"""

import asyncio

import pytest

from aios.core.agent import AgentRuntime
from aios.core.memory import MemoryManager
from aios.core.scheduler import scheduler


# ─── scheduler: overlapping runs of one agent leaked a slot forever ─────────

def test_overlapping_runs_do_not_leak_capacity():
    """Two runs of the SAME agent share one `_running` key; the second
    terminate() used to pop nothing and skip the decrement, so the ceiling was
    permanently reduced until every later run was refused."""
    start, term = scheduler._running_count, len(scheduler._running)

    class _P:
        started_at = 0
        state = None

    # `scheduler` is a process-global singleton and `terminate()` never prunes
    # `_processes`, so a stub left behind here is still there when a later test
    # calls `scheduler.summary()` — which reads `p.agent_id` and blew up with
    # `'_P' object has no attribute 'agent_id'`, failing two health tests that
    # have nothing to do with the scheduler.
    try:
        for _ in range(3):
            scheduler._processes["overlap"] = _P()
            scheduler._running["overlap"] = scheduler._processes["overlap"]
            scheduler._running_count += 1
        scheduler._running.clear()  # every slot was released elsewhere

        for _ in range(3):
            scheduler._processes["overlap"] = _P()
            scheduler.terminate("overlap")

        assert scheduler._running_count == start, "overlapping runs leaked a slot"
    finally:
        scheduler._processes.pop("overlap", None)
        scheduler._running.pop("overlap", None)


def test_clean_runs_leave_capacity_intact():
    class _P:
        started_at = 0
        state = None

    start = scheduler._running_count
    try:
        for _ in range(20):
            scheduler._processes["clean"] = _P()
            scheduler.start("clean")
            scheduler.terminate("clean")
        assert scheduler._running_count == start
    finally:
        scheduler._processes.pop("clean", None)
        scheduler._running.pop("clean", None)


# ─── memory: long-term extraction never fired, tier-2 summarize never ran ───

@pytest.mark.asyncio
async def test_user_turn_reaches_long_term_memory(tmp_path, monkeypatch):
    """Extractor returns None for anything but role='user', and no production
    path passed a user turn — so the vector store stayed empty and
    get_context_injections always returned nothing."""
    from aios.config import settings

    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    m = MemoryManager("agent-pt-extract")
    await m.note_user_turn("c1", "lembre-se: o cliente prefere ser contatado por email")
    hits = await m.search_hybrid("como o cliente prefere ser contatado", top_k=5)
    assert hits, "a PT-BR user turn produced no long-term memory"


@pytest.mark.asyncio
async def test_user_turn_extraction_does_not_touch_the_buffer(tmp_path, monkeypatch):
    from aios.config import settings

    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    m = MemoryManager("agent-pt-buffer")
    await m.note_user_turn("c1", "lembre-se: sempre agendar follow-up")
    assert m._buffers["c1"] == [], "note_user_turn duplicated the turn in the buffer"


@pytest.mark.asyncio
async def test_tier_two_summary_is_reachable(tmp_path, monkeypatch):
    """The gate was `len(buffer) % 20 == 0` on a buffer popped back to exactly
    50 every time; 50 % 20 == 10, so summarization never ran once."""
    from aios.config import settings

    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    m = MemoryManager("agent-tier2")
    calls = []

    async def _fake_summary(conv_id, content):
        calls.append(content)

    m._summarize = _fake_summary
    for i in range(70):
        await m.add("c2", "assistant", f"resposta {i} com texto suficiente para resumir")
    assert calls, "tier-2 summarization never fired"


# ─── memory: tool rows were replayed as orphan tool messages ───────────────

@pytest.mark.asyncio
async def test_tool_rows_are_not_replayed_into_context(tmp_path, monkeypatch):
    """role='tool' rows carry no tool_call_id and no preceding assistant
    tool_calls; every chat-completions API rejects them, so an agent that used
    one tool broke on its next turn."""
    from aios.config import settings

    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))

    class _Row:
        def __init__(self, role, content):
            self.role = role
            self.content = content

    class _Result:
        def scalars(self):
            return self

        def all(self):
            return [_Row("user", "oi"), _Row("tool", "{'ok': true}"), _Row("assistant", "pronto")]

    class _DB:
        async def execute(self, *_a, **_k):
            return _Result()

    m = MemoryManager("agent-toolrows")
    await m._load_from_db("c9", _DB())
    roles = [r["role"] for r in m._buffers["c9"]]
    assert "tool" not in roles, f"orphan tool message replayed: {roles}"
    assert roles == ["user", "assistant"]


# ─── approval: ask mode was unreachable, and the row had no org ────────────

def test_ask_autonomy_is_recognised():
    """`autonomy: "ask"` is the documented value and the only thing the schema
    mentions, but the gate only matched ask_tools/ask_all — so an agent set to
    ask before acting executed tools with no approval at all."""
    import inspect

    src = inspect.getsource(AgentRuntime._run_stream_inner)
    assert '"ask"' in src, "autonomy='ask' still bypasses the approval gate"


def test_approval_request_carries_org_id():
    """Without org_id the PendingAction row lands unscoped and the approvals
    API filters it out for every tenant: nobody could approve it and the agent
    waited out the full timeout."""
    import inspect

    src = inspect.getsource(AgentRuntime._run_stream_inner)
    assert "org_id=self.agent.org_id" in src, "approval row still written without org_id"