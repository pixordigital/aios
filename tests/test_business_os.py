"""Business OS decision ledger + AgentDB-backed context wiring."""
import pytest
from types import SimpleNamespace

from aios.core import business_os, second_brain


class _FakeAgentDB:
    def __init__(self):
        self.decisions = []
        self.knowledge = []
        self.reflections = []
        self.learnings = []

    async def put_knowledge(self, **kw):
        self.decisions.append(kw)

    async def search_knowledge(self, *, org_id, agent_id="", knowledge_type="", q="", limit=20):
        assert org_id
        return self.knowledge

    async def list_reflections(self, *, org_id, agent_id="", limit=20):
        return self.reflections

    async def list_learnings(self, *, org_id, agent_id="", limit=20):
        return self.learnings


@pytest.mark.asyncio
async def test_record_decision(monkeypatch):
    fake = _FakeAgentDB()
    monkeypatch.setattr(business_os, "agent_db", fake)
    await business_os.record_decision("a1", "org-1", "ship v2 at Friday noon")
    assert fake.decisions and fake.decisions[0]["knowledge_type"] == "decision"


@pytest.mark.asyncio
async def test_second_brain_includes_decisions(monkeypatch):
    fake = _FakeAgentDB()
    fake.knowledge = [SimpleNamespace(value="ship v2 Friday")]
    monkeypatch.setattr(second_brain, "agent_db", fake)
    out = await second_brain.get_second_brain_injections("a1", "org-1", "q")
    assert any("Decisão" in m["content"] or "Decisão" in (m["content"] or "") for m in out)
