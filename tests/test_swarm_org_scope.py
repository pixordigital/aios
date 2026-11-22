"""Tenant isolation for swarm tasks and shared memory.

list_tasks/stats/claim/complete/vote/list_messages/get_shared used to filter
by team_id or task_id alone. Any authenticated user could read another
tenant's payloads. Paths now require caller org_id and fail closed
(missing => not found/empty).
"""

from __future__ import annotations

import pytest

from aios.core.swarm import SwarmCoordinator
from aios.db.backend import db_session
from aios.db.models import Organization, SwarmMessage, SwarmTask, Team


@pytest.fixture
async def two_org_tasks():
    async with db_session() as db:
        for org_id, name in (("org-a", "Org A"), ("org-b", "Org B")):
            if not await db.get(Organization, org_id):
                db.add(Organization(id=org_id, name=name, slug=name.lower().replace(" ", "-")))
        team_a = Team(id="team-a", org_id="org-a", name="Team A")
        team_b = Team(id="team-b", org_id="org-b", name="Team B")
        db.add(team_a)
        db.add(team_b)
        await db.flush()
        db.add(SwarmTask(id="task-a1", team_id="team-a", org_id="org-a",
                         task_id="ext-a1", task_type="agent_call", payload={"secret": "a"}))
        db.add(SwarmTask(id="task-b1", team_id="team-b", org_id="org-b",
                         task_id="ext-b1", task_type="agent_call", payload={"secret": "b"}))
        await db.commit()
    yield
    async with db_session() as db:
        for tid in ("task-a1", "task-b1"):
            t = await db.get(SwarmTask, tid)
            if t:
                await db.delete(t)
        for tid in ("team-a", "team-b"):
            t = await db.get(Team, tid)
            if t:
                await db.delete(t)
        await db.commit()


@pytest.mark.asyncio
async def test_list_tasks_scoped_to_org(two_org_tasks) -> None:
    rows = await SwarmCoordinator().list_tasks(team_id="team-a", org_id="org-a")
    assert [t.id for t in rows] == ["task-a1"]
    assert await SwarmCoordinator().list_tasks(team_id="team-a", org_id="org-b") == []
    assert await SwarmCoordinator().list_tasks(team_id="team-a", org_id="") == []


@pytest.mark.asyncio
async def test_stats_scoped_to_org(two_org_tasks) -> None:
    s = await SwarmCoordinator().stats("team-a", org_id="org-a")
    assert s == {"total_tasks": 1, "queued": 1}
    assert await SwarmCoordinator().stats("team-a", org_id="org-b") == {"total_tasks": 0, "queued": 0}


@pytest.mark.asyncio
async def test_claim_complete_vote_reject_foreign_org(two_org_tasks) -> None:
    coord = SwarmCoordinator()
    assert await coord.claim("task-a1", "agent-x", "org-b") is None
    assert await coord.complete("task-a1", result={}, org_id="org-b") is None
    assert await coord.vote("task-a1", "agent-x", "approve", org_id="org-b") is None
    # own org still works
    assert await coord.vote("task-a1", "agent-x", "approve", org_id="org-a") is not None


@pytest.fixture
async def two_org_messages(two_org_tasks):
    async with db_session() as db:
        db.add(SwarmMessage(
            id="msg-a1", team_id="team-a", org_id="org-a",
            message_type="memory", content={"secret": "a"}, memory_key="k1",
        ))
        db.add(SwarmMessage(
            id="msg-b1", team_id="team-b", org_id="org-b",
            message_type="memory", content={"secret": "b"}, memory_key="k1",
        ))
        await db.commit()
    yield
    async with db_session() as db:
        for mid in ("msg-a1", "msg-b1"):
            m = await db.get(SwarmMessage, mid)
            if m:
                await db.delete(m)
        await db.commit()


@pytest.mark.asyncio
async def test_get_shared_scoped_to_org(two_org_messages) -> None:
    coord = SwarmCoordinator()
    msg = await coord.get_shared(team_id="team-a", key="k1", org_id="org-a")
    assert msg and msg.id == "msg-a1"
    assert await coord.get_shared(team_id="team-a", key="k1", org_id="org-b") is None
    assert await coord.get_shared(team_id="team-a", key="k1", org_id="") is None


@pytest.mark.asyncio
async def test_list_messages_scoped_to_org(two_org_messages) -> None:
    coord = SwarmCoordinator()
    rows = await coord.list_messages(team_id="team-a", org_id="org-a")
    assert [m.id for m in rows] == ["msg-a1"]
    assert await coord.list_messages(team_id="team-a", org_id="org-b") == []
    assert await coord.list_messages(team_id="team-a", org_id="") == []
