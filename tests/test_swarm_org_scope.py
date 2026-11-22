"""Tenant isolation for swarm tasks and shared memory.

list_tasks/stats/claim/complete/vote/list_messages/get_shared used to filter
by team_id or task_id alone. Any authenticated user could read another
tenant's payloads. Paths now require caller org_id and fail closed
(missing => not found/empty). Team-path consistency also enforced.
"""

from __future__ import annotations

import pytest

from httpx import ASGITransport, AsyncClient

from aios.api.deps import get_current_user, get_org_id
from aios.core.swarm import SwarmCoordinator
from aios.db.backend import db_session
from aios.db.models import Agent, Conversation, Organization, SwarmMessage, SwarmTask, Team, User, team_agents
from aios.main import app


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
        db.add(Agent(id="agent-a1", org_id="org-a", name="A1"))
        db.add(Agent(id="agent-a2", org_id="org-a", name="A2"))
        db.add(Agent(id="agent-b1", org_id="org-b", name="B1"))
        await db.flush()
        await db.execute(team_agents.insert().values(team_id="team-a", agent_id="agent-a1", priority=0))
        await db.execute(team_agents.insert().values(team_id="team-a", agent_id="agent-a2", priority=1))
        await db.execute(team_agents.insert().values(team_id="team-b", agent_id="agent-b1", priority=0))
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
        for mid in ("msg-a1", "msg-b1"):
            m = await db.get(SwarmMessage, mid)
            if m:
                await db.delete(m)
        await db.execute(team_agents.delete().where(team_agents.c.team_id.in_(["team-a", "team-b"])))
        for aid in ("agent-a1", "agent-a2", "agent-b1"):
            a = await db.get(Agent, aid)
            if a:
                await db.delete(a)
        for tid in ("team-a", "team-b"):
            t = await db.get(Team, tid)
            if t:
                await db.delete(t)
        for cid in ("conv-a", "conv-b"):
            c = await db.get(Conversation, cid)
            if c:
                await db.delete(c)
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
    assert await coord.claim("task-a1", "agent-a1", "org-b") is None
    assert await coord.complete("task-a1", result={}, org_id="org-b") is None
    assert await coord.vote("task-a1", "agent-a1", "approve", org_id="org-b") is None
    # own org still works for team member
    assert await coord.vote("task-a1", "agent-a1", "approve", org_id="org-a") is not None


@pytest.mark.asyncio
async def test_task_team_path_mismatch_rejected(two_org_tasks) -> None:
    coord = SwarmCoordinator()
    # task-a1 belongs to team-a; passing team-b (same org fixture has org-b team) must fail closed
    assert await coord.claim("task-a1", "agent-a1", "org-a", team_id="team-b") is None
    assert await coord.complete("task-a1", result={}, org_id="org-a", team_id="team-b") is None
    assert await coord.vote("task-a1", "agent-a1", "approve", org_id="org-a", team_id="team-b") is None
    # correct team path works for real member
    claimed = await coord.claim("task-a1", "agent-a1", "org-a", team_id="team-a")
    assert claimed is not None and claimed.status == "running"


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


@pytest.mark.asyncio
async def test_team_org_mismatch_fail_closed(two_org_tasks) -> None:
    coord = SwarmCoordinator()
    # team-a belongs to org-a; org-b must not dispatch/list/stats/memory on it
    assert await coord.dispatch(team_id="team-a", org_id="org-b", task_type="x") is None
    assert await coord.list_tasks(team_id="team-a", org_id="org-b") == []
    assert await coord.stats("team-a", org_id="org-b") == {"total_tasks": 0, "queued": 0}
    assert await coord.put_shared(team_id="team-a", org_id="org-b", key="k", content={"x": 1}) is None
    assert await coord.get_shared(team_id="team-a", key="k1", org_id="org-b") is None
    assert await coord.list_messages(team_id="team-a", org_id="org-b") == []


@pytest.mark.asyncio
async def test_config_scoped_to_org(two_org_tasks) -> None:
    coord = SwarmCoordinator()
    # ensure/get/create own org
    cfg = await coord.ensure_config("team-a", "org-a")
    assert cfg is not None
    assert cfg.team_id == "team-a"
    assert cfg.org_id == "org-a"
    got = await coord.get_config("team-a", org_id="org-a")
    assert got is not None and got.id == cfg.id
    # foreign org / missing org fail closed
    assert await coord.get_config("team-a", org_id="org-b") is None
    assert await coord.get_config("team-a", org_id="") is None
    assert await coord.ensure_config("team-a", "org-b") is None
    assert await coord.ensure_config("team-a", "") is None
    # update scoped
    upd = await coord.update_config("team-a", org_id="org-a", swarm_mode="mesh")
    assert upd is not None and upd.swarm_mode == "mesh"
    assert await coord.update_config("team-a", org_id="org-b", swarm_mode="pipeline") is None
    assert await coord.update_config("team-a", org_id="", swarm_mode="pipeline") is None
    # foreign org cannot read mutated value
    assert await coord.get_config("team-a", org_id="org-b") is None
    got2 = await coord.get_config("team-a", org_id="org-a")
    assert got2 is not None and got2.swarm_mode == "mesh"


@pytest.mark.asyncio
async def test_agent_membership_fail_closed(two_org_tasks) -> None:
    coord = SwarmCoordinator()
    # agent-b1 belongs to org-b/team-b, not team-a
    assert await coord.claim("task-a1", "agent-b1", "org-a", team_id="team-a") is None
    assert await coord.vote("task-a1", "agent-b1", "approve", org_id="org-a", team_id="team-a") is None
    assert await coord.dispatch(
        team_id="team-a", org_id="org-a", task_type="agent_call", agent_id="agent-b1"
    ) is None
    assert await coord.put_shared(
        team_id="team-a", org_id="org-a", key="k", content={"x": 1}, sender_id="agent-b1"
    ) is None


@pytest.mark.asyncio
async def test_dispatch_conversation_and_dep_ownership(two_org_tasks) -> None:
    coord = SwarmCoordinator()
    async with db_session() as db:
        db.add(Conversation(id="conv-a", org_id="org-a", team_id="team-a", channel="web"))
        db.add(Conversation(id="conv-b", org_id="org-b", team_id="team-b", channel="web"))
        await db.commit()
    created: list[str] = []
    try:
        assert await coord.dispatch(
            team_id="team-a", org_id="org-a", conversation_id="conv-b"
        ) is None
        t = await coord.dispatch(
            team_id="team-a", org_id="org-a", conversation_id="conv-a"
        )
        assert t is not None and t.conversation_id == "conv-a"
        created.append(t.id)
        assert await coord.dispatch(
            team_id="team-a", org_id="org-a", depends_on=["task-b1"]
        ) is None
        t2 = await coord.dispatch(
            team_id="team-a", org_id="org-a", depends_on=["task-a1"]
        )
        assert t2 is not None and t2.depends_on == ["task-a1"]
        created.append(t2.id)
    finally:
        async with db_session() as db:
            for tid in created:
                row = await db.get(SwarmTask, tid)
                if row:
                    await db.delete(row)
            for cid in ("conv-a", "conv-b"):
                c = await db.get(Conversation, cid)
                if c:
                    await db.delete(c)
            await db.commit()


@pytest.mark.asyncio
async def test_consensus_denominator_uses_real_members(two_org_tasks) -> None:
    coord = SwarmCoordinator()
    async with db_session() as db:
        db.add(SwarmTask(
            id="task-consensus", team_id="team-a", org_id="org-a",
            task_id="ext-consensus", task_type="consensus", payload={}
        ))
        await db.commit()
    try:
        # team-a has 2 members, threshold default .6; one approval not enough
        t = await coord.vote("task-consensus", "agent-a1", "approve", org_id="org-a", team_id="team-a")
        assert t is not None
        assert t.status in ("queued", "assigned", "running", "consensus")  # not done
        assert t.status != "done"
        # second approval reaches 2/2
        t = await coord.vote("task-consensus", "agent-a2", "approve", org_id="org-a", team_id="team-a")
        assert t is not None and t.status == "done"
        assert t.result["consensus"] == "approved"
    finally:
        async with db_session() as db:
            t = await db.get(SwarmTask, "task-consensus")
            if t:
                await db.delete(t)
            await db.commit()


@pytest.mark.asyncio
async def test_dispatch_idempotency_key_dedupes(two_org_tasks) -> None:
    coord = SwarmCoordinator()
    created: list[str] = []
    try:
        t1 = await coord.dispatch(
            team_id="team-a", org_id="org-a", task_type="agent_call",
            payload={"idempotency_key": "idem-1", "x": 1},
        )
        t2 = await coord.dispatch(
            team_id="team-a", org_id="org-a", task_type="agent_call",
            payload={"idempotency_key": "idem-1", "x": 2},
        )
        t3 = await coord.dispatch(
            team_id="team-a", org_id="org-a", task_type="agent_call",
            payload={"x": 3}, idempotency_key="idem-1",
        )
        assert t1 is not None
        created.append(t1.id)
        assert t2 is not None and t2.id == t1.id
        assert t3 is not None and t3.id == t1.id
        # Different key creates new task
        t4 = await coord.dispatch(
            team_id="team-a", org_id="org-a", task_type="agent_call",
            payload={"idempotency_key": "idem-2"},
        )
        assert t4 is not None and t4.id != t1.id
        created.append(t4.id)
    finally:
        async with db_session() as db:
            for tid in created:
                row = await db.get(SwarmTask, tid)
                if row:
                    await db.delete(row)
            await db.commit()


@pytest.mark.asyncio
async def test_complete_terminal_state_guard(two_org_tasks) -> None:
    coord = SwarmCoordinator()
    async with db_session() as db:
        db.add(SwarmTask(
            id="task-term", team_id="team-a", org_id="org-a",
            task_id="ext-term", task_type="agent_call", payload={}, status="running",
        ))
        await db.commit()
    try:
        done = await coord.complete("task-term", result={"ok": True}, org_id="org-a", team_id="team-a")
        assert done is not None and done.status == "done"
        # same-status idempotent no-op
        again = await coord.complete("task-term", result={"ok": True}, org_id="org-a", team_id="team-a")
        assert again is not None and again.status == "done"
        # different terminal rejected
        conflict = await coord.complete("task-term", error="boom", org_id="org-a", team_id="team-a")
        assert conflict is None
        async with db_session() as db:
            row = await db.get(SwarmTask, "task-term")
            assert row is not None
            assert row.status == "done"
            assert row.error == ""
    finally:
        async with db_session() as db:
            row = await db.get(SwarmTask, "task-term")
            if row:
                await db.delete(row)
            await db.commit()


@pytest.mark.asyncio
async def test_vote_rejects_terminal_overwrite(two_org_tasks) -> None:
    coord = SwarmCoordinator()
    async with db_session() as db:
        db.add(SwarmTask(
            id="task-vote-term", team_id="team-a", org_id="org-a",
            task_id="ext-vote-term", task_type="consensus", payload={},
            status="done", result={"consensus": "approved"},
            consensus_votes={"agent-a1": "approve", "agent-a2": "approve"},
        ))
        await db.commit()
    try:
        same = await coord.vote("task-vote-term", "agent-a1", "approve", org_id="org-a", team_id="team-a")
        assert same is not None and same.status == "done"
        conflict = await coord.vote("task-vote-term", "agent-a1", "reject", org_id="org-a", team_id="team-a")
        assert conflict is None
    finally:
        async with db_session() as db:
            row = await db.get(SwarmTask, "task-vote-term")
            if row:
                await db.delete(row)
            await db.commit()


@pytest.mark.asyncio
async def test_claim_rejects_non_claimable_status(two_org_tasks) -> None:
    coord = SwarmCoordinator()
    async with db_session() as db:
        db.add(SwarmTask(
            id="task-done", team_id="team-a", org_id="org-a",
            task_id="ext-done", task_type="agent_call", payload={}, status="done",
        ))
        await db.commit()
    try:
        assert await coord.claim("task-done", "agent-a1", "org-a", team_id="team-a") is None
    finally:
        async with db_session() as db:
            row = await db.get(SwarmTask, "task-done")
            if row:
                await db.delete(row)
            await db.commit()


@pytest.fixture
async def swarm_api_client(two_org_tasks):
    async with db_session() as db:
        user = await db.get(User, "user-a")
        if not user:
            user = User(
                id="user-a",
                org_id="org-a",
                email="a@test.local",
                hashed_password="test-hash",
                role="admin",
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

    app.dependency_overrides[get_org_id] = lambda: "org-a"
    app.dependency_overrides[get_current_user] = lambda: user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.pop(get_org_id, None)
    app.dependency_overrides.pop(get_current_user, None)
    async with db_session() as db:
        row = await db.get(User, "user-a")
        if row:
            await db.delete(row)
            await db.commit()


@pytest.mark.asyncio
async def test_api_claim_conflict_vs_not_found(swarm_api_client) -> None:
    async with db_session() as db:
        db.add(SwarmTask(
            id="task-api-done", team_id="team-a", org_id="org-a",
            task_id="ext-api-done", task_type="agent_call", payload={}, status="done",
        ))
        await db.commit()
    try:
        resp = await swarm_api_client.post(
            "/api/swarms/team-a/tasks/task-api-done/claim",
            params={"agent_id": "agent-a1"},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"] == "task not claimable: status=done"

        missing = await swarm_api_client.post(
            "/api/swarms/team-a/tasks/nope/claim",
            params={"agent_id": "agent-a1"},
        )
        assert missing.status_code == 404
        assert missing.json()["detail"] == "task not found"
    finally:
        async with db_session() as db:
            row = await db.get(SwarmTask, "task-api-done")
            if row:
                await db.delete(row)
                await db.commit()


@pytest.mark.asyncio
async def test_api_complete_conflict_vs_not_found(swarm_api_client) -> None:
    async with db_session() as db:
        db.add(SwarmTask(
            id="task-api-complete", team_id="team-a", org_id="org-a",
            task_id="ext-api-complete", task_type="agent_call", payload={}, status="done",
        ))
        await db.commit()
    try:
        # Same-status complete is idempotent in core; different terminal is conflict.
        idem = await swarm_api_client.post(
            "/api/swarms/team-a/tasks/task-api-complete/complete",
        )
        assert idem.status_code == 200

        resp = await swarm_api_client.post(
            "/api/swarms/team-a/tasks/task-api-complete/complete",
            params={"error": "boom"},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"] == "task not completable: status=done"

        missing = await swarm_api_client.post(
            "/api/swarms/team-a/tasks/nope/complete",
        )
        assert missing.status_code == 404
        assert missing.json()["detail"] == "task not found"
    finally:
        async with db_session() as db:
            row = await db.get(SwarmTask, "task-api-complete")
            if row:
                await db.delete(row)
                await db.commit()


@pytest.mark.asyncio
async def test_api_vote_conflict_vs_not_found(swarm_api_client) -> None:
    async with db_session() as db:
        db.add(SwarmTask(
            id="task-api-vote", team_id="team-a", org_id="org-a",
            task_id="ext-api-vote", task_type="consensus", payload={}, status="failed",
        ))
        await db.commit()
    try:
        resp = await swarm_api_client.post(
            "/api/swarms/team-a/tasks/task-api-vote/vote",
            params={"agent_id": "agent-a1", "vote": "approve"},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"] == "task not votable: status=failed"

        missing = await swarm_api_client.post(
            "/api/swarms/team-a/tasks/nope/vote",
            params={"agent_id": "agent-a1", "vote": "approve"},
        )
        assert missing.status_code == 404
        assert missing.json()["detail"] == "task not found"
    finally:
        async with db_session() as db:
            row = await db.get(SwarmTask, "task-api-vote")
            if row:
                await db.delete(row)
                await db.commit()
