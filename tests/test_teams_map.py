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
        db.add(Organization(id="o9r", name="O", slug="o9r"))
        db.add(Conversation(id="c9r", org_id="o9r", agent_id="a9r"))
        await db.flush()
        db.add(Message(conversation_id="c9r", org_id="o9r", role="user",
                       content="oi", agent_id="a9r", created_at=now))
        db.add(Message(conversation_id="c9r", org_id="o9r", role="user",
                       content="velha", agent_id="a8r",
                       created_at=now - timedelta(hours=2)))
        await db.commit()
        act = await _recent_activity(db, "o9r", minutes=30)
    assert set(act) == {"a9r"}
    # outside the window the agent is simply absent, not "inactive"
    assert "a8r" not in act


async def test_recent_activity_never_raises():
    from aios.dashboard.app import _recent_activity

    assert await _recent_activity(None, "nope") == {}


async def test_map_data_route_shape():
    """The poll payload: graph for structure, activity for liveness + ops."""
    import types

    import aios.dashboard.app as app_mod
    from aios.db.backend import db_session
    from aios.db.models import Agent, Organization, Team

    async with db_session() as db:
        db.add(Organization(id="o7s", name="O", slug="o7s"))
        db.add(Agent(id="a7s", name="Ag", org_id="o7s", status="active"))
        await db.flush()
        db.add(Team(id="t7s", name="T", org_id="o7s", agents=[]))
        await db.commit()
    req = types.SimpleNamespace(state=types.SimpleNamespace(org_id="o7s"))
    out = await app_mod.team_map_data(req)
    assert out["ok"] is True
    assert {n["id"] for n in out["graph"]["nodes"]} >= {"team:t7s", "agent:a7s"}
    assert out["activity"] == {}
    assert set(out["ops"]) >= {"pending_approvals", "routines", "routine_badges", "failed_night_jobs", "generated_at"}
    assert out["ops"]["pending_approvals"] == {"total": 0, "by_agent": {}, "by_team": {}}
    assert out["ops"]["failed_night_jobs"] == {"total": 0, "recent": []}


def test_build_teams_map_ops_empty_safe():
    import aios.dashboard.app as app_mod

    ops = app_mod._build_teams_map_ops(teams=[], pending_rows=[], routines=[], now=None)
    assert ops["pending_approvals"]["total"] == 0
    assert ops["routines"] == []
    assert ops["routine_badges"] == {"by_agent": {}, "by_team": {}}
    assert ops["failed_night_jobs"]["total"] == 0
    assert ops["generated_at"]


def test_build_teams_map_ops_counts_and_badges():
    from datetime import datetime, timezone
    import types

    import aios.dashboard.app as app_mod

    now = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
    a1 = types.SimpleNamespace(id="a1")
    a2 = types.SimpleNamespace(id="a2")
    t1 = types.SimpleNamespace(id="t1", agents=[a1, a2])
    pending = [types.SimpleNamespace(agent_id="a1"), types.SimpleNamespace(agent_id="a1"), types.SimpleNamespace(agent_id="a2")]
    routines = [
        types.SimpleNamespace(routine_id="r1", name="Night backup", source_type="fixed_tick", enabled=True, mode="proactive",
                              last_status="failed", last_run_at=now, next_run_at=now, job_name="backup_tick", agent_id="a1", team_id=None),
        types.SimpleNamespace(routine_id="r2", name="Reactive", source_type="event_subscription", enabled=True, mode="reactive",
                              last_status="ok", last_run_at=now, next_run_at=now, job_name="evt", agent_id="a2", team_id="t1"),
    ]
    ops = app_mod._build_teams_map_ops(teams=[t1], pending_rows=pending, routines=routines, now=now)
    assert ops["pending_approvals"] == {"total": 3, "by_agent": {"a1": 2, "a2": 1}, "by_team": {"t1": 3}}
    assert ops["routine_badges"]["by_agent"]["a1"] == "failed"
    assert ops["routine_badges"]["by_team"]["t1"] == "failed"
    assert ops["failed_night_jobs"]["total"] == 1
    assert ops["failed_night_jobs"]["recent"][0]["routine_id"] == "r1"
    assert len(ops["routines"]) == 2
    assert set(ops["routines"][0]) >= {"routine_id", "name", "source_type", "enabled", "mode", "last_status", "last_run_at", "next_run_at", "job_name"}


async def test_map_data_ops_org_isolation_and_degradation(monkeypatch):
    import types
    from datetime import datetime, timezone

    import aios.dashboard.app as app_mod
    from aios.db.backend import db_session
    from aios.db.models import Agent, Conversation, Organization, PendingAction, Team

    async with db_session() as db:
        db.add(Organization(id="oA", name="A", slug="oa"))
        db.add(Organization(id="oB", name="B", slug="ob"))
        db.add(Agent(id="aA", name="A1", org_id="oA", status="active"))
        db.add(Agent(id="aB", name="B1", org_id="oB", status="active"))
        await db.flush()
        db.add(Team(id="tA", name="TA", org_id="oA", agents=[]))
        db.add(Team(id="tB", name="TB", org_id="oB", agents=[]))
        db.add(Conversation(id="cA", org_id="oA", agent_id="aA"))
        db.add(Conversation(id="cB", org_id="oB", agent_id="aB"))
        await db.flush()
        db.add(PendingAction(id="pA", org_id="oA", agent_id="aA", conversation_id="cA", tool_name="x", tool_args={}, status="pending"))
        db.add(PendingAction(id="pB", org_id="oB", agent_id="aB", conversation_id="cB", tool_name="x", tool_args={}, status="pending"))
        await db.commit()

    req_a = types.SimpleNamespace(state=types.SimpleNamespace(org_id="oA"))
    out_a = await app_mod.team_map_data(req_a)
    assert out_a["ops"]["pending_approvals"]["total"] == 1
    assert out_a["ops"]["pending_approvals"]["by_agent"] == {"aA": 1}

    async def boom(*_a, **_k):
        raise RuntimeError("routines down")

    monkeypatch.setattr("aios.core.routines.list_routines", boom)
    req_b = types.SimpleNamespace(state=types.SimpleNamespace(org_id="oB"))
    out_b = await app_mod.team_map_data(req_b)
    assert out_b["ok"] is True
    assert out_b["ops"]["pending_approvals"]["total"] == 1
    assert out_b["ops"]["pending_approvals"]["by_agent"] == {"aB": 1}
    assert out_b["ops"]["routines"] == []
    assert out_b["ops"]["routine_badges"] == {"by_agent": {}, "by_team": {}}
