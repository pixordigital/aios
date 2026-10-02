"""Tenant isolation for swarm tasks.

list_tasks/stats/claim/complete/vote used to filter by team_id or task_id
alone. Any authenticated user could read another tenant's task payloads by
team_id, and claim/complete/vote cross-tenant tasks. All five paths now
require the caller's org_id and fail closed (missing => not found).
"""

from __future__ import annotations

import pytest

from aios.core.swarm import SwarmCoordinator
from aios.db.backend import db_session
from aios.db.models import Organization, SwarmTask, Team


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
