"""Tests for Hermes/HyperAgent-inspired features.

Approval mode, skills, rubrics, FTS5 memory, three-part extraction.
Pure-logic tests (no DB) where possible; API tests for CRUD.
"""

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import select


# ─── Three-part memory extraction ───

def test_extractor_three_part():
    from aios.core.memory import Extractor
    ex = Extractor()
    assert ex.extract("user", "my name is joao, remember that")["type"] == "fact"
    assert ex.extract("user", "remember to always summarize long responses")["type"] == "skill"
    assert ex.extract("user", "remember you should always be polite")["type"] == "rubric"
    # no memory signal → nothing
    assert ex.extract("user", "what time is it") is None
    # non-user role → nothing
    assert ex.extract("assistant", "remember this") is None


@pytest.mark.asyncio(loop_scope="function")
async def test_fts_hybrid_search(tmp_path, monkeypatch):
    from aios.config import settings
    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    from aios.core.memory import MemoryManager
    m = MemoryManager("fts-test-agent")
    await m._store_vector("user prefers dark theme for reports")
    await m._store_vector("quarterly deadline is Friday")
    # exact keyword via FTS
    fts = await m.search_fts("dark theme", top_k=3)
    assert any("dark theme" in r["content"] for r in fts)
    # hybrid merges both
    hybrid = await m.search_hybrid("dark theme", top_k=3)
    assert hybrid
    # cross-conversation loader
    cross = await m.get_agent_memories(top_k=10)
    assert len(cross) == 2


def test_fts_vector_db_has_fts_table(tmp_path, monkeypatch):
    from aios.config import settings
    monkeypatch.setattr(settings, "app_data_dir", str(tmp_path))
    from aios.core.memory import _vec_db
    conn = _vec_db("fts-schema-check")
    vtables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'memories%'"
    ).fetchall()]
    assert "memories_fts" in vtables


# ─── Approval manager ───

@pytest.mark.asyncio(loop_scope="function")
async def test_approval_approve_flow():
    from aios.core.approval import ApprovalManager
    am = ApprovalManager(timeout=5.0)

    async def requester():
        return await am.request_approval(
            "a1", "agent1", "conv1", "web_search", {"q": "x"}
        )

    async def decider():
        await asyncio.sleep(0.1)
        assert am.approve("id1") is False  # unknown id
        ok = am.approve("a1", decided_by="user9")
        return ok

    task1 = asyncio.create_task(requester())
    task2 = asyncio.create_task(decider())
    approved = await task1
    await task2
    assert approved is True


@pytest.mark.asyncio(loop_scope="function")
async def test_approval_reject_flow():
    from aios.core.approval import ApprovalManager
    am = ApprovalManager(timeout=5.0)

    async def requester():
        return await am.request_approval("a2", "t2", "c2", "delete_file", "{}")

    async def decider():
        await asyncio.sleep(0.1)
        am.reject("a2", decided_by="user9")

    task1 = asyncio.create_task(requester())
    task2 = asyncio.create_task(decider())
    approved = await task1
    await task2
    assert approved is False


@pytest.mark.asyncio(loop_scope="function")
async def test_approval_timeout():
    from aios.core.approval import ApprovalManager
    am = ApprovalManager(timeout=0.2)
    # no decider → times out → not approved
    approved = await am.request_approval("a3", "t3", "c3", "tool_x", "{}")
    assert approved is False
    assert am.get_pending("t3") == []


# ─── Rubric scoring ───

@pytest.mark.asyncio(loop_scope="function")
async def test_rubric_create_and_score():
    from aios.core.rubric import rubric_manager
    r = rubric_manager.create("quality", criteria=["accurate", "clear"])
    res = await rubric_manager.score_response(r.id, "A clear, accurate response.", llm_provider=None)
    assert res["rubric_id"] == r.id
    assert "total_score" in res
    assert 0 <= res["total_score"] <= 10
    assert list(res["scores"].keys()) == ["accurate", "clear"]


@pytest.mark.asyncio(loop_scope="function")
async def test_rubric_unknown_returns_error():
    from aios.core.rubric import rubric_manager
    assert "error" in await rubric_manager.score_response("nope", "anything")


# ─── Meta agent ───

@pytest.mark.asyncio(loop_scope="function")
async def test_meta_agent_evaluate_and_history():
    from aios.core.meta_agent import meta_agent
    res = await meta_agent.evaluate("m-agent", "say hello", "hi there!", llm_provider=None)
    assert res["total_score"] >= 0
    assert res["suggestions"]
    hist = meta_agent.history("m-agent")
    assert any(h["id"] == res["eval_id"] for h in hist)


# ─── API: skills CRUD ───

@pytest.mark.asyncio(loop_scope="function")
async def test_skills_crud(auth_client, test_org, test_session):
    # need an agent for FK
    from aios.db.models import Agent
    agent = Agent(name="test-agent", org_id=test_org.id)
    test_session.add(agent)
    await test_session.commit()
    await test_session.refresh(agent)
    agent_id = agent.id

    # create
    r = await auth_client.post("/api/skills", json={
        "agent_id": agent_id, "name": "summarize", "description": "compress long text"
    })
    assert r.status_code == 200, r.text
    skill_id = r.json()["id"]
    assert r.json()["name"] == "summarize"

    # list
    r = await auth_client.get("/api/skills")
    assert r.status_code == 200
    assert any(s["id"] == skill_id for s in r.json()["skills"])

    # search
    r = await auth_client.get("/api/skills", params={"q": "compress"})
    assert any(s["id"] == skill_id for s in r.json()["skills"])

    # apply increments usage
    r = await auth_client.post(f"/api/skills/{skill_id}/apply")
    assert r.status_code == 200
    assert r.json()["skill_id"] == skill_id

    # delete
    r = await auth_client.delete(f"/api/skills/{skill_id}")
    assert r.status_code == 200
    r = await auth_client.delete(f"/api/skills/{skill_id}")
    assert r.status_code == 404


# ─── API: rubrics ───

@pytest.mark.asyncio(loop_scope="function")
async def test_rubrics_api(auth_client):
    r = await auth_client.post("/api/rubrics", json={
        "name": "quality", "criteria": ["clear", "accurate"]
    })
    assert r.status_code == 200, r.text
    rid = r.json()["id"]

    r = await auth_client.get("/api/rubrics")
    assert r.status_code == 200
    assert any(x["id"] == rid for x in r.json()["rubrics"])

    r = await auth_client.post("/api/rubrics/score", json={
        "rubric_id": rid, "response": "A clear and accurate answer."
    })
    assert r.status_code == 200
    assert r.json()["total_score"] >= 0