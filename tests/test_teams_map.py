"""Unit tests for the teams map canvas data (_team_graph).

The canvas only draws what this returns, so every relation the map claims is
pinned here: leadership edges, membership edges, shared agents, orphans.
"""

import types
from datetime import UTC

from aios.dashboard.app import _team_graph


def _agent(id, name="Ag", status="active"):
    return types.SimpleNamespace(id=id, name=name, status=status)


def _team(id, name="Time", agents=(), orch=None, mgr=None, strategy="supervisor"):
    return types.SimpleNamespace(
        id=id, name=name, agents=list(agents),
        orchestrator_agent_id=orch, manager_agent_id=mgr,
        routing_strategy=strategy,
    )


def _by_id(graph, kind, id):
    return next(n for n in graph["nodes"] if n["kind"] == kind and n["id"] == f"{kind}:{id}")


# ─── relations ────────────────────────────────────────────────────────────

def test_leadership_and_membership_edges():
    a1, a2, a3 = _agent("a1", "Orq"), _agent("a2", "Mgr"), _agent("a3", "Membro")
    t = _team("t1", agents=[a1, a2, a3], orch="a1", mgr="a2")
    g = _team_graph([t], [a1, a2, a3])
    kinds = {(e["from"], e["to"], e["kind"]) for e in g["edges"]}
    assert ("agent:a1", "team:t1", "orchestrator") in kinds
    assert ("agent:a2", "team:t1", "manager") in kinds
    assert ("team:t1", "agent:a3", "member") in kinds
    # leaders are not ALSO drawn as plain members of the same team
    assert ("team:t1", "agent:a1", "member") not in kinds
    assert ("team:t1", "agent:a2", "member") not in kinds


def test_same_agent_as_orchestrator_and_manager_drawn_once():
    a1 = _agent("a1")
    t = _team("t1", agents=[a1], orch="a1", mgr="a1")
    g = _team_graph([t], [a1])
    assert len([e for e in g["edges"] if "a1" in e["from"] or "a1" in e["to"]]) == 1


def test_dangling_role_ids_are_skipped():
    """An orchestrator id pointing at an agent outside the org (or deleted)
    must not produce an edge to a node that does not exist."""
    t = _team("t1", agents=[], orch="ghost")
    g = _team_graph([t], [])
    assert g["edges"] == []
    assert [n for n in g["nodes"] if n["kind"] == "team"]


def test_shared_agent_flagged():
    a = _agent("a1", "Ponte")
    t1 = _team("t1", agents=[a])
    t2 = _team("t2", agents=[a])
    g = _team_graph([t1, t2], [a])
    assert _by_id(g, "agent", "a1")["shared"] is True
    assert ("team:t1", "agent:a1", "member") in {(e["from"], e["to"], e["kind"]) for e in g["edges"]}
    assert ("team:t2", "agent:a1", "member") in {(e["from"], e["to"], e["kind"]) for e in g["edges"]}


def test_orphan_agent_listed_as_orphan():
    a = _agent("a9", "Solto")
    g = _team_graph([], [a])
    node = _by_id(g, "agent", "a9")
    assert node["orphan"] is True and node["shared"] is False
    assert g["edges"] == []


def test_empty_org_is_valid():
    assert _team_graph([], []) == {"nodes": [], "edges": []}


# ─── node payload the canvas needs ────────────────────────────────────────

def test_nodes_carry_links_and_labels():
    a = _agent("a1", "SDR", status="active")
    t = _team("t1", "Comercial", agents=[a], strategy="supervisor")
    g = _team_graph([t], [a])
    team = _by_id(g, "team", "t1")
    assert team["label"] == "Comercial" and team["strategy"] == "supervisor"
    assert team["url"] == "/dashboard/teams/t1/edit"
    agent = _by_id(g, "agent", "a1")
    assert agent["label"] == "SDR" and agent["status"] == "active"
    assert agent["url"] == "/dashboard/agents/a1/edit"


# ─── live payload ─────────────────────────────────────────────────────────

async def test_recent_activity_groups_by_agent():
    """One grouped query: agent_id -> latest message time inside the window.
    Read from message rows (true cross-process) rather than in-process
    scheduler/health state the dashboard process never sees."""
    from datetime import datetime, timedelta

    from aios.dashboard.app import _recent_activity
    from aios.db.backend import db_session
    from aios.db.models import Conversation, Message, Organization

    now = datetime.now(UTC)
    async with db_session() as db:
        db.add(Organization(id="o9", name="O", slug="o9"))
        db.add(Conversation(id="c9", org_id="o9", agent_id="a9"))
        await db.flush()
        db.add(Message(conversation_id="c9", org_id="o9", role="user",
                       content="oi", agent_id="a9", created_at=now))
        db.add(Message(conversation_id="c9", org_id="o9", role="user",
                       content="velha", agent_id="a8",
                       created_at=now - timedelta(hours=2)))
        await db.commit()
        act = await _recent_activity(db, "o9", minutes=30)
    assert set(act) == {"a9"}
    # outside the window the agent is simply absent, not "inactive"
    assert "a8" not in act


async def test_recent_activity_never_raises():
    from aios.dashboard.app import _recent_activity

    assert await _recent_activity(None, "nope") == {}


async def test_map_data_route_shape():
    """The poll payload: graph for structure, activity for liveness."""
    import types

    import aios.dashboard.app as app_mod
    from aios.db.backend import db_session
    from aios.db.models import Agent, Organization, Team

    async with db_session() as db:
        db.add(Organization(id="o7", name="O", slug="o7"))
        db.add(Agent(id="a7", name="Ag", org_id="o7", status="active"))
        await db.flush()
        db.add(Team(id="t7", name="T", org_id="o7", agents=[]))
        await db.commit()
    req = types.SimpleNamespace(state=types.SimpleNamespace(org_id="o7"))
    out = await app_mod.team_map_data(req)
    assert out["ok"] is True
    assert {n["id"] for n in out["graph"]["nodes"]} >= {"team:t7", "agent:a7"}
    assert out["activity"] == {}
