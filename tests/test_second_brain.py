"""Second brain: retrieval injection + consolidation into AgentDB."""
from types import SimpleNamespace

import pytest

from aios.core import second_brain
from aios.core.agent_db import agent_db


class _FakeAgentDB:
    def __init__(self):
        self.reflections = [
            SimpleNamespace(key_insight="fix auth first", what_went_well="")
        ]
        self.learnings = [SimpleNamespace(outcome="worked", action_taken="x", success=True)]
        self.knowledge = []
        self.puts = []
        self.learnings_written = []

    async def list_reflections(self, *, org_id, agent_id="", limit=20):
        assert org_id
        return self.reflections

    async def list_learnings(self, *, org_id, agent_id="", limit=20):
        return self.learnings

    async def search_knowledge(self, *, org_id, agent_id="", q="", limit=20):
        return self.knowledge

    async def put_knowledge(self, **kw):
        self.puts.append(kw)

    async def record_learning(self, **kw):
        self.learnings_written.append(kw)


@pytest.mark.asyncio
async def test_retrieval_injects_reflections_and_learnings(monkeypatch):
    fake = _FakeAgentDB()
    monkeypatch.setattr(second_brain, "agent_db", fake)
    out = await second_brain.get_second_brain_injections("a1", "org-1", "auth")
    assert len(out) == 1
    assert out[0]["role"] == "system"
    assert "fix auth first" in out[0]["content"]
    assert "worked" in out[0]["content"]


@pytest.mark.asyncio
async def test_retrieval_returns_empty_without_org(monkeypatch):
    fake = _FakeAgentDB()
    monkeypatch.setattr(second_brain, "agent_db", fake)
    assert await second_brain.get_second_brain_injections("a1", "", "q") == []
    assert await second_brain.get_second_brain_injections("a1", "org-1", "q")


@pytest.mark.asyncio
async def test_consolidation_writes_knowledge_and_learning(monkeypatch):
    fake = _FakeAgentDB()
    monkeypatch.setattr(second_brain, "agent_db", fake)
    import aios.core.agent_db as adb
    monkeypatch.setattr(adb, "_pattern_sig", lambda t, a: "sig", raising=True)

    # stub db_session count to 0 duplicates
    class _DB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, stmt):
            class _R:
                def scalar(self):
                    return 0

            return _R()

    monkeypatch.setattr("aios.db.backend.db_session", lambda: _DB(), raising=True)
    await second_brain.consolidate_reflection("a1", "org-1", "c1", ["insight alpha", "beta"])
    assert fake.puts and fake.puts[0]["agent_id"] == "a1"
    assert fake.learnings_written and fake.learnings_written[0]["learning_type"] == "success_pattern"
