"""Tests for Hermes/HyperAgent-inspired features.

Approval mode, skills, rubrics, FTS5 memory, three-part extraction.
Pure-logic tests (no DB) where possible; API tests for CRUD.
"""

import asyncio
import json

import pytest


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
        assert await am.approve("id1") is False  # unknown id
        ok = await am.approve("a1", decided_by="user9")
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
        await am.reject("a2", decided_by="user9")

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


def _hitl_runtime(governance_config: dict):
    """Agent that requests one high-value tool call on its first LLM turn."""
    import types
    import uuid

    from aios.core.agent import AgentRuntime

    uid = str(uuid.uuid4())
    agent = types.SimpleNamespace(
        id=f"hitl-agent-{uid}", org_id=f"hitl-org-{uid}", tools=["crm_update_deal"],
        llm_config={"model": "openai/gpt-4o", "temperature": 0.7, "max_tokens": 4096},
        governance_config=governance_config, name="t", system_prompt="hi",
        memory_config={}, extra_data={},
    )
    rt = AgentRuntime(agent)
    turns = []

    async def _stream(*, messages, model, **kw):
        turns.append(model)
        if len(turns) == 1:
            yield {"type": "tool_call", "tool_calls": [{
                "id": "c1", "function": {
                    "name": "crm_update_deal", "arguments": '{"value": 9000}',
                },
            }]}
        else:
            yield {"type": "token", "content": "done"}
        yield {"type": "done"}

    executed = []

    async def _execute(name, args):
        executed.append((name, args))
        return "ok"

    rt._llm_chat_stream = _stream
    rt.tool_engine.execute = _execute
    return rt, executed


@pytest.mark.asyncio(loop_scope="function")
async def test_hitl_gate_blocks_tool_until_human_approves(monkeypatch):
    from aios.core import approval as approval_module

    seen = []

    async def _request(**kwargs):
        seen.append(kwargs)
        return False

    monkeypatch.setattr(approval_module.approval_manager, "request_approval", _request)
    rt, executed = _hitl_runtime({
        "autonomy": "autonomous", "hitl_enabled": True, "hitl_value_threshold": 5000,
    })
    [ev async for ev in rt.run_stream("c-hitl-deny", "update deal")]

    assert len(seen) == 1
    assert seen[0]["tool_name"] == "crm_update_deal"
    assert seen[0]["org_id"] == rt.agent.org_id
    assert seen[0]["tool_args"] == {"value": 9000}
    assert "HITL:" in seen[0]["context_summary"]
    assert executed == []


@pytest.mark.asyncio(loop_scope="function")
async def test_hitl_gate_executes_approved_tool(monkeypatch):
    from aios.core import approval as approval_module

    async def _request(**kwargs):
        return True

    monkeypatch.setattr(approval_module.approval_manager, "request_approval", _request)
    rt, executed = _hitl_runtime({
        "autonomy": "autonomous", "hitl_enabled": True, "hitl_value_threshold": 5000,
    })
    [ev async for ev in rt.run_stream("c-hitl-ok", "update deal")]

    assert executed == [("crm_update_deal", '{"value": 9000}')]


@pytest.mark.asyncio(loop_scope="function")
async def test_hitl_disabled_does_not_gate_tool(monkeypatch):
    from aios.core import approval as approval_module

    seen = []

    async def _request(**kwargs):
        seen.append(kwargs)
        return True

    monkeypatch.setattr(approval_module.approval_manager, "request_approval", _request)
    rt, executed = _hitl_runtime({
        "autonomy": "autonomous", "hitl_enabled": False, "hitl_value_threshold": 5000,
    })
    [ev async for ev in rt.run_stream("c-hitl-off", "update deal")]

    assert seen == []
    assert executed == [("crm_update_deal", '{"value": 9000}')]


@pytest.mark.parametrize("tool,args,needs_hitl", [
    ("crm_delete_deal", '{"deal_id": "d1"}', True),
    ("crm_update_deal", '{"deal_id": "d1", "stage": "closed_won"}', True),
    ("sql_query", '{"query": "DELETE FROM crm_deals"}', True),
    ("send_email", json.dumps({"to": [f"u{i}@x.com" for i in range(100)]}), True),
    ("sql_query", '{"query": "SELECT * FROM crm_deals"}', False),
    ("calculator", '{"expression": "2+2"}', False),
])
def test_hitl_risk_rules(tool, args, needs_hitl):
    rt, _ = _hitl_runtime({"hitl_enabled": True, "hitl_value_threshold": 5000})
    assert bool(rt._hitl_tool_reason(tool, args)) is needs_hitl


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


# ─── API: approval decision authorization ───

async def _seed_action(test_session, org_id, *, action_id, tool_args=None):
    from aios.db.models import PendingAction

    row = PendingAction(
        id=action_id, org_id=org_id, agent_id="agent-x", conversation_id="conv-x",
        tool_name="crm_update_deal", tool_args=tool_args or {}, status="pending",
    )
    test_session.add(row)
    await test_session.commit()
    await test_session.refresh(row)
    return row


@pytest.mark.asyncio(loop_scope="function")
async def test_approval_decision_requires_privileged_role(auth_client, test_org, test_user, test_session):
    test_user.role = "member"
    await test_session.commit()
    row = await _seed_action(test_session, test_org.id, action_id="role-denied")
    for verb in ("approve", "reject"):
        r = await auth_client.post(f"/api/approvals/{row.id}/{verb}")
        assert r.status_code == 403, r.text
    await test_session.refresh(row)
    assert row.status == "pending"


@pytest.mark.asyncio(loop_scope="function")
async def test_approval_decision_owner_can_approve(auth_client, test_org, test_user, test_session):
    test_user.role = "owner"
    await test_session.commit()
    row = await _seed_action(test_session, test_org.id, action_id="owner-approve")
    r = await auth_client.post(f"/api/approvals/{row.id}/approve")
    assert r.status_code == 200, r.text
    await test_session.refresh(row)
    assert row.status == "approved"


@pytest.mark.asyncio(loop_scope="function")
async def test_approval_decision_founder_id_can_reject(auth_client, test_org, test_user, test_session):
    test_user.role = "member"
    test_org.extra_data = {**(test_org.extra_data or {}), "founder_user_id": test_user.id}
    await test_session.commit()
    row = await _seed_action(test_session, test_org.id, action_id="founder-reject")
    r = await auth_client.post(f"/api/approvals/{row.id}/reject")
    assert r.status_code == 200, r.text
    await test_session.refresh(row)
    assert row.status == "rejected"


@pytest.mark.asyncio(loop_scope="function")
async def test_approval_decision_blocks_self_approval(auth_client, test_org, test_user, test_session):
    test_user.role = "owner"
    await test_session.commit()
    mine = await _seed_action(
        test_session, test_org.id, action_id="self-approve",
        tool_args={"requested_by": test_user.id},
    )
    r = await auth_client.post(f"/api/approvals/{mine.id}/approve")
    assert r.status_code == 403, r.text
    own = await _seed_action(
        test_session, test_org.id, action_id="self-reject",
        tool_args={"created_by": test_user.id},
    )
    r = await auth_client.post(f"/api/approvals/{own.id}/reject")
    assert r.status_code == 403, r.text
    await test_session.refresh(mine)
    await test_session.refresh(own)
    assert mine.status == own.status == "pending"


@pytest.mark.asyncio(loop_scope="function")
async def test_approval_decision_org_scope_and_missing_org_fail_closed(
    auth_client, test_org, second_org, test_user, test_session
):
    row = await _seed_action(test_session, second_org.id, action_id="other-org")
    r = await auth_client.post(f"/api/approvals/{row.id}/approve")
    assert r.status_code == 404, r.text

    test_user.org_id = "missing-org"
    await test_session.commit()
    row = await _seed_action(test_session, "missing-org", action_id="no-org")
    r = await auth_client.post(f"/api/approvals/{row.id}/approve")
    assert r.status_code == 403, r.text
    await test_session.refresh(row)
    assert row.status == "pending"