"""Shared state: channel leases, agent health, telemetry read path."""

import asyncio
from types import SimpleNamespace

import pytest

from aios.channels.email_ import EmailChannel
from aios.db.models import Agent, AgentMetric, Message


class FakeLeasePool:
    def __init__(self):
        self.data = {}

    async def set(self, key, value, nx=False, ex=None, xx=False):
        if nx and key in self.data:
            return None
        if xx and key not in self.data:
            return None
        self.data[key] = value
        return True

    async def eval(self, script, numkeys, key, owner, ttl=None):
        if self.data.get(key) != owner:
            return 0
        if "del" in script:
            self.data.pop(key, None)
        return 1


@pytest.mark.asyncio(loop_scope="function")
async def test_lease_is_exclusive_and_owner_scoped():
    from aios.tasks.queue import acquire_lease, release_lease, renew_lease

    pool = FakeLeasePool()
    assert await acquire_lease(pool, "k", "owner-a", 60)
    assert not await acquire_lease(pool, "k", "owner-b", 60), "second replica won the lease"
    assert await renew_lease(pool, "k", "owner-a", 60)
    assert not await renew_lease(pool, "k", "owner-b", 60), "renewed someone else's lease"
    assert not await release_lease(pool, "k", "owner-b")
    assert await release_lease(pool, "k", "owner-a")
    assert "k" not in pool.data


@pytest.mark.asyncio(loop_scope="function")
async def test_imap_lease_waits_then_reports_loss(monkeypatch):
    pool = FakeLeasePool()

    async def fake_pool():
        return pool

    monkeypatch.setattr("aios.tasks.queue.get_redis_pool", fake_pool)
    ch = EmailChannel(
        connection=SimpleNamespace(id="c1", config={"email": "a@b.c"}, org_id="o1")
    )

    assert await ch._claim_mailbox("aios:imap-poll:a@b.c") == "ok"
    assert await ch._claim_mailbox("aios:imap-poll:a@b.c") == "ok"
    pool.data.pop("aios:imap-poll:a@b.c")  # lease expired / taken
    assert await ch._claim_mailbox("aios:imap-poll:a@b.c") == "lost"


class FakeHealthPool:
    def __init__(self, data=None):
        self.data = dict(data or {})

    async def set(self, key, value, ex=None):
        self.data[key] = value
        return True

    async def keys(self, pattern):
        return list(self.data)

    async def mget(self, keys):
        return [self.data.get(k) for k in keys]


@pytest.mark.asyncio(loop_scope="function")
async def test_health_status_is_published_to_redis(monkeypatch):
    from aios.core.agent_health import AgentHealthTracker

    pool = FakeHealthPool()

    async def fake_pool():
        return pool

    monkeypatch.setattr("aios.tasks.queue.get_redis_pool", fake_pool)
    monkeypatch.setattr("aios.core.agent_health._escalate", lambda *a, **k: None)

    tracker = AgentHealthTracker()
    for _ in range(5):
        tracker.record_failure("agent-1")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert pool.data.get("aios:health:agent-1") == "degraded"


@pytest.mark.asyncio(loop_scope="function")
async def test_health_refresh_applies_shared_stopped_status(monkeypatch):
    from aios.core.agent_health import AgentHealthTracker

    pool = FakeHealthPool({"aios:health:agent-2": "stopped"})

    async def fake_pool():
        return pool

    monkeypatch.setattr("aios.tasks.queue.get_redis_pool", fake_pool)

    tracker = AgentHealthTracker()
    assert tracker.is_available("agent-2")  # local view starts healthy
    assert await tracker.refresh() == 1
    assert tracker.is_available("agent-2") is False


@pytest.mark.asyncio(loop_scope="function")
async def test_context_cache_is_ignored_when_another_turn_landed(
    test_db_session, test_org
):
    import time

    from aios.core.agent import _cached_context_is_fresh
    from aios.core.context_manager import SavedContext
    from aios.db.models import Conversation

    conv = Conversation(org_id=test_org.id, channel="web")
    test_db_session.add(conv)
    await test_db_session.commit()
    await test_db_session.refresh(conv)

    cached = SavedContext(
        conversation_id=conv.id,
        agent_id="agent-1",
        message_block=[{"role": "assistant", "content": "old"}],
        message_count=21,
        saved_at=time.time() - 60,
    )

    # One newer row = the current user message; the cache is still current.
    test_db_session.add(
        Message(conversation_id=conv.id, org_id=test_org.id, role="user", content="hi")
    )
    await test_db_session.commit()
    assert await _cached_context_is_fresh(test_db_session, conv.id, cached) is True

    # A second row means another turn was answered after this cache was saved.
    test_db_session.add(
        Message(conversation_id=conv.id, org_id=test_org.id, role="assistant", content="yo")
    )
    await test_db_session.commit()
    assert await _cached_context_is_fresh(test_db_session, conv.id, cached) is False


@pytest.mark.asyncio(loop_scope="function")
async def test_telemetry_summary_reads_persisted_rows(
    auth_client, test_db_session, test_org, test_user
):
    agent = Agent(
        org_id=test_org.id,
        name="Metrics Agent",
        agent_type="custom",
        llm_config={"model": "test/model"},
        system_prompt="p",
        tools=[],
        governance_config={},
    )
    test_db_session.add(agent)
    await test_db_session.commit()
    await test_db_session.refresh(agent)

    test_db_session.add_all(
        [
            AgentMetric(
                agent_id=agent.id,
                org_id=test_org.id,
                hour="2026-11-16-10",
                messages=4,
                tokens=40,
                errors=1,
                avg_response_ms=100,
                samples=2,
            ),
            AgentMetric(
                agent_id=agent.id,
                org_id=test_org.id,
                hour="2026-11-16-11",
                messages=6,
                tokens=60,
                errors=0,
                avg_response_ms=300,
                samples=2,
            ),
        ]
    )
    await test_db_session.commit()

    resp = await auth_client.get("/api/analytics/telemetry/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_messages"] == 10
    assert body["total_tokens"] == 100
    assert body["total_errors"] == 1
    assert body["active_agents"] == 1
    # weighted by samples: (100*2 + 300*2) / 4
    assert body["avg_response_ms"] == 200
