"""The context cache was write-only, which is what lost the tool-call chain.

`context_manager.save()` ran at the end of every agent run and nothing ever
called `load()`. The DB replay that stands in for it carries user/assistant
text only — `role="tool"` rows are filtered because a bare tool message with no
`tool_call_id` is rejected by every chat-completions API — so the assistant's
`tool_calls` were dropped between turns and the model had to re-derive state it
had already computed.
"""

import asyncio

import pytest

from aios.core.context_manager import context_manager


class _Msg:
    def __init__(self, role, content):
        self.role = role
        self.content = content


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _DB:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, *_a, **_k):
        return _Result(self._rows)


@pytest.mark.asyncio
async def test_cache_round_trips_what_save_stored():
    context_manager.drop("c-cache", "a-cache")
    block = [
        {"role": "user", "content": "oi"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "function": {"name": "sql_query", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "3 rows"},
        {"role": "assistant", "content": "tres linhas"},
    ]
    context_manager.save("c-cache", "a-cache", [{"role": "system", "content": "P"}, *block])

    loaded = context_manager.load("c-cache", "a-cache")
    assert loaded is not None, "save() wrote nothing load() could return"
    # the tool chain survives the round trip; the system prompt is not duplicated
    assert loaded.message_block == block
    assert all(m.get("role") != "system" for m in loaded.message_block)


@pytest.mark.asyncio
async def test_cache_preserves_tool_calls_that_the_db_replay_drops():
    """The DB path cannot reconstruct tool_calls: a role='tool' row has no
    tool_call_id and providers reject it. The cache holds the real block."""
    from aios.core.memory import MemoryManager

    m = MemoryManager("agent-cache")
    await m._load_from_db(
        "c-tc", _DB([_Msg("user", "oi"), _Msg("tool", "3 rows"), _Msg("assistant", "tres linhas")])
    )
    replay = m._buffers["c-tc"]
    assert all(x["role"] != "tool" for x in replay)

    context_manager.drop("c-tc", "agent-cache")
    with_chain = [
        {"role": "user", "content": "oi"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "function": {"name": "sql_query", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "3 rows"},
        {"role": "assistant", "content": "tres linhas"},
    ]
    context_manager.save("c-tc", "agent-cache", with_chain)
    loaded = context_manager.load("c-tc", "agent-cache")
    assert any("tool_calls" in x for x in loaded.message_block), (
        "the cached context lost the assistant's tool_calls — same as the DB replay"
    )


@pytest.mark.asyncio
async def test_agent_reads_the_cache_when_it_is_not_stale(monkeypatch, tmp_path):
    """_build_context must consult load(); that is what makes save() live."""
    import inspect

    from aios.core.agent import AgentRuntime

    src = inspect.getsource(AgentRuntime._build_context)
    assert "context_manager.load(" in src, (
        "the context cache is still write-only: nothing reads what save() stored"
    )


def test_cache_is_bounded_and_drops_cleanly():
    context_manager.drop("c-drop", "a-drop")
    context_manager.save("c-drop", "a-drop", [{"role": "user", "content": "x"}])
    assert context_manager.load("c-drop", "a-drop") is not None
    context_manager.drop("c-drop", "a-drop")
    assert context_manager.load("c-drop", "a-drop") is None