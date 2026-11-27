"""Phase 5 slice 1: conversation ingest -> second brain."""
import pytest
from types import SimpleNamespace

from aios.core import second_brain


class _FakeAgentDB:
    def __init__(self):
        self.knowledge = []

    async def put_knowledge(self, **kw):
        self.knowledge.append(kw)

    async def search_knowledge(self, *, org_id, agent_id="", knowledge_type="", q="", limit=20):
        return self.knowledge

    async def list_reflections(self, *, org_id, agent_id="", limit=20):
        return []

    async def list_learnings(self, *, org_id, agent_id="", limit=20):
        return []


@pytest.mark.asyncio
async def test_ingest_conversation_writes_knowledge(monkeypatch):
    fake = _FakeAgentDB()
    monkeypatch.setattr(second_brain, "agent_db", fake)
    await second_brain.ingest_conversation("a1", "org-1", "yt-28lKPCja5jk", "Conteudo do video do Alan Nicolas.", source="youtube")
    assert len(fake.knowledge) == 1
    k = fake.knowledge[0]
    assert k["knowledge_type"] == "reflection"
    assert k["source"] == "youtube"
    assert k["extra_data"]["conversation_id"] == "yt-28lKPCja5jk"


@pytest.mark.asyncio
async def test_ingest_conversation_empty_text_noop(monkeypatch):
    fake = _FakeAgentDB()
    monkeypatch.setattr(second_brain, "agent_db", fake)
    await second_brain.ingest_conversation("a1", "org-1", "c1", "  ")
    assert fake.knowledge == []
