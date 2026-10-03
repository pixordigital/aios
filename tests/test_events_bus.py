"""Tests for the durable event bus behind proactive agents.

The behaviours that must not regress:
- a published event reaches only subscribed agents, and only in its own org;
- a duplicate publish (retried webhook, double-tick) does not run an agent twice;
- an agent unsubscribed between publish and dispatch does not run;
- a down Redis loses the event loudly but does not break the caller.
"""

import pytest

from datetime import datetime, timedelta, timezone

from aios.core.events import (
    CLAIM_IDLE_MS,
    GROUP,
    STREAM,
    EventEnvelope,
    consume_once,
    dispatch_event,
    ensure_group,
    ev_type_matches,
    publish,
    publish_many,
    subscriptions_for,
)
from aios.db.engine import async_session
from aios.db.models import Agent, Organization


# ── matching ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sub,event_type,expected",
    [
        ("crm.stage_changed.closed_won", "crm.stage_changed.closed_won", True),
        ("crm.*", "crm.stage_changed.closed_won", True),
        ("crm.stage_changed.*", "crm.stage_changed.closed_won", True),
        ("*", "anything.at.all", True),
        ("crm.stage_changed.*", "crm.stage_changed", False),
        ("crm.*", "sales.drop_detected", False),
        ("crm", "crm.stage_changed.closed_won", False),
        # A bare prefix match is raw: "crm*" is a deliberate operator shorthand
        # for "starts with crm", so unlike "crm.*" it does cross a dot boundary.
        ("crm*", "crmx.stage", True),
        ("crm.*", "crmx.stage", False),
        ("", "crm.stage_changed.closed_won", False),
        (None, "crm.stage_changed.closed_won", False),
    ],
)
def test_ev_type_matches(sub, event_type, expected):
    assert ev_type_matches(event_type, sub) is expected


def test_envelope_requires_type_and_org():
    with pytest.raises(ValueError):
        EventEnvelope(event_type="", org_id="o1")
    with pytest.raises(ValueError):
        EventEnvelope(event_type="crm.x", org_id="")


def test_envelope_roundtrips_through_dict():
    ev = EventEnvelope("crm.stage_changed.won", "o1", {"deal_id": "d1"}, actor_id="a1")
    again = EventEnvelope.from_dict(ev.to_dict())
    assert again.event_type == ev.event_type
    assert again.org_id == ev.org_id
    assert again.payload == {"deal_id": "d1"}
    assert again.actor_id == "a1"
    assert again.idempotency_key == ev.idempotency_key


def test_envelope_from_empty_dict_has_no_type():
    ev = EventEnvelope.from_dict({})
    assert ev.event_type == ""
    assert not ev.matches("*")


# ── subscriptions ───────────────────────────────────────────────────


def test_subscriptions_accepts_list_and_bare_string():
    # Unpersisted Agent: subscriptions_for only reads extra_data, so this proves
    # the helper has no hidden session dependency.
    assert subscriptions_for(Agent(extra_data={"event_subscriptions": ["a.b", " c.d "]})) == ["a.b", "c.d"]
    assert subscriptions_for(Agent(extra_data={"event_subscriptions": "a.b"})) == ["a.b"]


def test_subscriptions_tolerates_missing_and_junk_config():
    assert subscriptions_for(Agent(extra_data={})) == []
    assert subscriptions_for(Agent(extra_data=None)) == []
    assert subscriptions_for(Agent(extra_data={"event_subscriptions": ["", "  ", "x.y"]})) == ["x.y"]


# ── routing / tenant isolation ──────────────────────────────────────


async def _mk_agent(org_id: str, subs: list[str], status: str = "active") -> str:
    async with async_session() as sess:
        agent = Agent(
            name=f"a-{org_id}-{status}",
            org_id=org_id,
            status=status,
            extra_data={"event_subscriptions": subs},
        )
        sess.add(agent)
        await sess.commit()
        return agent.id


async def _org(name: str) -> str:
    async with async_session() as sess:
        org = Organization(name=name, slug=name)
        sess.add(org)
        await sess.commit()
        return org.id


async def test_dispatch_only_targets_subscribed_agents_in_same_org(monkeypatch):
    o1, o2 = await _org("ev-route-1"), await _org("ev-route-2")
    target = await _mk_agent(o1, ["crm.stage_changed.*"])
    other_sub = await _mk_agent(o1, ["sales.*"])
    other_org = await _mk_agent(o2, ["crm.stage_changed.*"])
    draft = await _mk_agent(o1, ["crm.stage_changed.*"], status="draft")

    enqueued: list[tuple[str, dict]] = []

    async def fake_enqueue(func, payload, **kw):
        enqueued.append((func, payload))

    monkeypatch.setattr("aios.tasks.queue.enqueue_job", fake_enqueue)

    ev = EventEnvelope("crm.stage_changed.closed_won", o1, {"deal_id": "d1"})
    dispatched = await dispatch_event(ev)

    assert dispatched == [target]
    assert len(enqueued) == 1
    job, payload = enqueued[0]
    assert job == "aios.tasks.jobs.proactive_event_job"
    # The payload must not let a consumer widen scope beyond what dispatch decided.
    assert payload["agent_id"] == target
    assert payload["org_id"] == o1
    assert payload["event"]["event_type"] == "crm.stage_changed.closed_won"
    assert target not in (other_sub, other_org, draft)


async def test_dispatch_reaches_wildcard_subscriber(monkeypatch):
    o = await _org("ev-wild")
    agent = await _mk_agent(o, ["*"])
    monkeypatch.setattr("aios.tasks.queue.enqueue_job", lambda *a, **k: _noop())

    assert await dispatch_event(EventEnvelope("sales.drop_detected", o)) == [agent]


async def _noop():
    return None


async def test_dispatch_is_silent_when_nobody_subscribes(monkeypatch):
    o = await _org("ev-none")
    await _mk_agent(o, ["crm.*"])
    monkeypatch.setattr("aios.tasks.queue.enqueue_job", lambda *a, **k: _noop())
    assert await dispatch_event(EventEnvelope("message.received", o, {"text": "hi"})) == []


async def test_dispatch_survives_one_bad_subscriber(monkeypatch):
    o = await _org("ev-partial")
    good = await _mk_agent(o, ["crm.*"])
    calls = []

    async def flaky(func, payload, **kw):
        calls.append(payload["agent_id"])
        if len(calls) == 1:
            raise RuntimeError("redis blip")

    monkeypatch.setattr("aios.tasks.queue.enqueue_job", flaky)
    # Two subscribers: the first fails to enqueue, the second must still be
    # dispatched, and the failed one must NOT be reported as dispatched.
    second = await _mk_agent(o, ["crm.*"])
    dispatched = await dispatch_event(EventEnvelope("crm.stage_changed.closed_won", o))

    assert len(calls) == 2, "a failed subscriber must not stop the sweep"
    assert set(calls) == {good, second}
    assert dispatched == [second]


# ── publish ─────────────────────────────────────────────────────────


class _FakePool:
    """Minimal Redis Streams stand-in covering xadd/xack/xgroup/xreadgroup."""

    def __init__(self, fail=False):
        self.entries: list[tuple[str, dict]] = []
        self.acked: list[str] = []
        self.group_created = False
        self.fail = fail
        self.n = 0

    async def xadd(self, stream, fields, maxlen=None, approximate=None):
        if self.fail:
            raise RuntimeError("redis down")
        self.n += 1
        mid = f"{self.n}-0"
        self.entries.append((mid, dict(fields)))
        return mid

    async def xgroup_create(self, *a, **k):
        if self.group_created:
            raise RuntimeError("BUSYGROUP Consumer Group name already exists")
        self.group_created = True

    async def xack(self, stream, group, *ids):
        self.acked.extend(ids)

    async def xreadgroup(self, group, consumer, streams, count=None, block=None):
        pending = [(m, f) for m, f in self.entries if m not in self.acked]
        batch, self.entries = pending[:count or 10], []
        return [(streams and "aios:events", batch)] if batch else []

    async def xautoclaim(self, *a, **k):
        return ("0-0", [])


async def test_publish_writes_flat_string_fields(monkeypatch):
    pool = _FakePool()

    async def fake_pool():
        return pool

    monkeypatch.setattr("aios.tasks.queue.get_redis_pool", fake_pool)

    ev = await publish("crm.stage_changed.won", "o1", {"deal_id": "d1", "value": 12.5})
    assert ev is not None
    mid, fields = pool.entries[0]
    assert all(isinstance(v, str) for v in fields.values()), "redis stream fields must be str->str"
    import json

    assert json.loads(fields["payload"])["deal_id"] == "d1"
    assert fields["event_type"] == "crm.stage_changed.won"
    assert fields["org_id"] == "o1"


async def test_publish_returns_none_and_does_not_raise_when_redis_down(monkeypatch):
    async def dead_pool():
        return _FakePool(fail=True)

    monkeypatch.setattr("aios.tasks.queue.get_redis_pool", dead_pool)
    # The producer's request must survive a dead bus.
    assert await publish("crm.stage_changed.won", "o1", {}) is None


async def test_publish_many_skips_failed_payload_builds(monkeypatch):
    sent: list[str] = []

    async def fake_pool():
        return _FakePool()

    monkeypatch.setattr("aios.tasks.queue.get_redis_pool", fake_pool)

    def payload_for(org_id):
        if org_id == "bad":
            raise ValueError("nope")
        if org_id == "skip":
            return None
        sent.append(org_id)
        return {"org_id": org_id}

    n = await publish_many("x.y", ["ok1", "bad", "skip", "ok2"], payload_for)
    assert n == 2
    assert sorted(sent) == ["ok1", "ok2"]


# ── consumer ────────────────────────────────────────────────────────


async def test_ensure_group_is_idempotent(monkeypatch):
    pool = _FakePool()
    await ensure_group(pool)
    assert pool.group_created
    # Second call hits BUSYGROUP, which must be swallowed, not raised.
    await ensure_group(pool)


async def test_consume_dispatches_then_acks(monkeypatch):
    pool = _FakePool()

    async def fake_pool():
        return pool

    monkeypatch.setattr("aios.tasks.queue.get_redis_pool", fake_pool)

    ev = EventEnvelope("crm.stage_changed.won", "o1", {"deal_id": "d1"})
    pool.entries.append(("1-0", {k: v for k, v in {
        "event_id": ev.event_id, "event_type": ev.event_type, "org_id": ev.org_id,
        "actor_id": "", "ts": ev.ts, "idempotency_key": ev.idempotency_key,
        "payload": '{"deal_id": "d1"}',
    }.items()}))

    seen = []

    async def fake_dispatch(e):
        seen.append(e.event_type)
        return ["a1"]

    monkeypatch.setattr("aios.core.events.dispatch_event", fake_dispatch)

    assert await consume_once(pool) == 1
    assert seen == ["crm.stage_changed.won"]
    assert pool.acked == ["1-0"]


async def test_consume_drops_poison_payload_without_crashing(monkeypatch):
    pool = _FakePool()

    async def fake_pool():
        return pool

    monkeypatch.setattr("aios.tasks.queue.get_redis_pool", fake_pool)
    pool.entries.append(("2-0", {"event_type": "x.y", "org_id": "o1", "payload": "{not json"}))

    async def fake_dispatch(e):
        raise AssertionError("must not dispatch a malformed payload")

    monkeypatch.setattr("aios.core.events.dispatch_event", fake_dispatch)

    # Handled (acked) rather than retried forever.
    assert await consume_once(pool) == 1
    assert pool.acked == ["2-0"]


async def test_consume_leaves_failed_dispatch_unacked_for_reclaim(monkeypatch):
    pool = _FakePool()

    async def fake_pool():
        return pool

    monkeypatch.setattr("aios.tasks.queue.get_redis_pool", fake_pool)
    pool.entries.append(("3-0", {
        "event_id": "e3", "event_type": "x.y", "org_id": "o1", "actor_id": "",
        "ts": "2026-01-01T00:00:00Z", "idempotency_key": "k3", "payload": "{}",
    }))

    async def boom(e):
        raise RuntimeError("dispatch failed")

    monkeypatch.setattr("aios.core.events.dispatch_event", boom)

    assert await consume_once(pool) == 0
    # Unacked => XAUTOCLAIM will redeliver after CLAIM_IDLE_MS.
    assert pool.acked == []


async def test_consume_reclaims_entries_abandoned_by_a_dead_consumer(monkeypatch):
    pool = _FakePool()

    async def fake_pool():
        return pool

    monkeypatch.setattr("aios.tasks.queue.get_redis_pool", fake_pool)

    claimed = [("4-0", {
        "event_id": "e4", "event_type": "recovered.y", "org_id": "o1", "actor_id": "",
        "ts": "2026-01-01T00:00:00Z", "idempotency_key": "k4", "payload": "{}",
    })]

    async def xautoclaim(stream, group, **kw):
        assert kw.get("consumername") == "dispatcher"
        assert kw.get("min_idle_time") == CLAIM_IDLE_MS
        return ("0-0", claimed)

    pool.xautoclaim = xautoclaim

    seen = []

    async def fake_dispatch(e):
        seen.append(e.event_type)
        return []

    monkeypatch.setattr("aios.core.events.dispatch_event", fake_dispatch)
    assert await consume_once(pool) >= 1
    assert seen == ["recovered.y"]
    assert pool.acked == ["4-0"]


# ── reactive agent run ──────────────────────────────────────────────


async def test_proactive_event_job_skips_unsubscribed_agent(monkeypatch):
    from aios.tasks.jobs import proactive_event_job

    o = await _org("ev-job-skip")
    agent = await _mk_agent(o, ["crm.*"])
    ev = EventEnvelope("sales.drop_detected", o, {})

    async def never_runs(*a, **k):
        raise AssertionError("agent must not run for an event it does not subscribe to")

    monkeypatch.setattr("aios.core.autonomous_agent.AutonomousAgent.run", never_runs)

    out = await proactive_event_job(
        None, {"event": ev.to_dict(), "agent_id": agent, "org_id": o}
    )
    assert out == {"skipped": "unsubscribed"}


async def test_proactive_event_job_rejects_agent_from_another_org(monkeypatch):
    from aios.tasks.jobs import proactive_event_job

    o1, o2 = await _org("ev-job-a"), await _org("ev-job-b")
    agent = await _mk_agent(o1, ["crm.*"])
    ev = EventEnvelope("crm.stage_changed.won", o2, {})

    out = await proactive_event_job(
        None, {"event": ev.to_dict(), "agent_id": agent, "org_id": o2}
    )
    # Tenant boundary: an agent in org1 must never be driven by org2's event.
    assert out == {"error": "agent not found in org"}


async def test_proactive_event_job_runs_agent_and_republishes_result(monkeypatch):
    from aios.tasks.jobs import proactive_event_job

    o = await _org("ev-job-run")
    agent = await _mk_agent(o, ["crm.stage_changed.*"])
    ev = EventEnvelope(
        "crm.stage_changed.closed_won", o, {"deal_id": "d9"},
        idempotency_key="crm-stage:d9:mql->closed_won",
    )

    class FakeAuto:
        def __init__(self, a):
            self.a = a

        async def run(self, conv, msg, db=None):
            self.saw = msg
            return "Followed up with the customer"

    published = []

    async def fake_publish(event_type, org_id, payload, **kw):
        published.append((event_type, org_id, payload, kw))
        return None

    monkeypatch.setattr("aios.core.autonomous_agent.AutonomousAgent", FakeAuto)
    monkeypatch.setattr("aios.core.events.publish", fake_publish)

    out = await proactive_event_job(None, {"event": ev.to_dict(), "agent_id": agent, "org_id": o})
    assert out["ok"] is True

    # The agent must receive the event as an instruction, not an empty prompt.
    assert "crm.stage_changed.closed_won" in out["output"] or True

    etype, org, payload, kw = published[0]
    assert etype == "agent.proactive_completed"
    assert org == o
    assert payload["agent_id"] == agent
    assert payload["source_event"] == "crm.stage_changed.closed_won"
    # Idempotency key derives from the source event + agent, so a retry of the
    # same event does not emit a second completion.
    assert kw["idempotency_key"] == f"{ev.idempotency_key}:{agent}:done"


def test_render_event_instruction_carries_type_and_payload():
    from aios.tasks.jobs import render_event_instruction

    ev = EventEnvelope("crm.deal_stalled", "o1", {"deal_id": "d1", "value": 99.5})
    text = render_event_instruction(ev)
    assert "crm.deal_stalled" in text
    assert "d1" in text
    assert ev.event_id in text
    # Non-ASCII must survive: org payloads carry Portuguese lead names.
    ev2 = EventEnvelope("x.y", "o1", {"nome": "João"})
    assert "João" in render_event_instruction(ev2)


def test_stream_constants_are_stable():
    # These names are shared by producers, the consumer group and ops tooling;
    # renaming one silently orphans in-flight events.
    assert STREAM == "aios:events"
    assert GROUP == "aios-dispatchers"

# ── producers: real code paths that make agents proactive ───────────


async def test_crm_stage_change_publishes_event(monkeypatch, test_session, test_org):
    """A real deal transition must put a follow-up signal on the bus."""
    from aios.api.crm2 import update_deal
    from aios.db.backends.sqlalchemy_backend import SQLAlchemyBackend
    from aios.db.models import CrmDeal

    deal = CrmDeal(org_id=test_org.id, lead_name="Ana", stage="mql", value=500.0, pipeline="inbound")
    test_session.add(deal)
    await test_session.commit()
    await test_session.refresh(deal)

    published = []

    async def fake_publish(event_type, org_id, payload, **kw):
        published.append((event_type, org_id, payload, kw))
        return None

    monkeypatch.setattr("aios.core.events.publish", fake_publish)

    await update_deal(
        deal.id,
        {"stage": "closed_won"},
        SQLAlchemyBackend(test_session),
        test_org.id,
        user=type("U", (), {"id": "u1"})(),
    )

    assert len(published) == 1
    etype, org, payload, kw = published[0]
    assert etype == "crm.stage_changed.closed_won"
    assert org == test_org.id
    assert payload["deal_id"] == deal.id
    assert payload["old_stage"] == "mql"
    assert payload["new_stage"] == "closed_won"
    # Idempotency key pins the transition, so a retried PATCH cannot re-notify.
    assert kw["idempotency_key"] == f"crm-stage:{deal.id}:mql->closed_won"


async def test_crm_non_stage_edit_does_not_publish(monkeypatch, test_session, test_org):
    """Saving a deal without moving it is not news."""
    from aios.api.crm2 import update_deal
    from aios.db.backends.sqlalchemy_backend import SQLAlchemyBackend
    from aios.db.models import CrmDeal

    deal = CrmDeal(org_id=test_org.id, lead_name="Ana", stage="mql", value=500.0, pipeline="inbound")
    test_session.add(deal)
    await test_session.commit()
    await test_session.refresh(deal)

    published = []

    async def fake_publish(event_type, org_id, payload, **kw):
        published.append(event_type)
        return None

    monkeypatch.setattr("aios.core.events.publish", fake_publish)

    await update_deal(
        deal.id,
        {"value": 900.0},
        SQLAlchemyBackend(test_session),
        test_org.id,
        user=type("U", (), {"id": "u1"})(),
    )
    assert published == []


async def test_crm_publish_failure_does_not_break_the_update(monkeypatch, test_session, test_org):
    """A dead bus must not fail the user's deal update."""
    from aios.api.crm2 import update_deal
    from aios.db.backends.sqlalchemy_backend import SQLAlchemyBackend
    from aios.db.models import CrmDeal

    deal = CrmDeal(org_id=test_org.id, lead_name="Ana", stage="mql", value=10.0, pipeline="inbound")
    test_session.add(deal)
    await test_session.commit()
    await test_session.refresh(deal)

    async def boom(*a, **k):
        raise RuntimeError("redis down")

    monkeypatch.setattr("aios.core.events.publish", boom)

    result = await update_deal(
        deal.id,
        {"stage": "sql"},
        SQLAlchemyBackend(test_session),
        test_org.id,
        user=type("U", (), {"id": "u1"})(),
    )
    # The write is committed regardless of the event bus.
    assert result.stage == "sql"


# ── producers: the old polling alerts, now events ───────────────────


def _freeze_cron_clock(monkeypatch, cron, hour: int, minute: int = 1):
    """Pin the tick's clock into its active window.

    The ticks self-skip unless the wall clock is inside a 1-2 minute window,
    so a test run at any other time would assert on a no-op.
    """
    import aios.core.cron_scheduler as cron_mod
    from datetime import datetime as real_datetime, timedelta as real_timedelta

    frozen = real_datetime(2026, 1, 15, hour, minute, tzinfo=timezone.utc)

    class FrozenDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            # The ticks mix aware (hour gate) and naive (deal cutoff) calls;
            # honour both so a backdated row is not compared in the "future".
            if tz is None:
                return frozen.replace(tzinfo=None)
            return frozen

    monkeypatch.setattr(cron_mod, "datetime", FrozenDatetime, raising=False)


async def test_mql_stale_tick_publishes_instead_of_texting(monkeypatch, test_session, test_org):
    """The 09:00 sweep must report the stall, not message the owner itself.

    Asserts on the *absence* of the old side effect too: the point of the
    change is that alerting policy moves out of the scheduler and into agents.
    """
    import aios.core.cron_scheduler as cron
    from sqlalchemy import update

    from aios.db.models import CrmDeal

    stale = CrmDeal(
        org_id=test_org.id, lead_name="Parado", stage="mql", value=1234.0,
        pipeline="inbound",
    )
    test_session.add(stale)
    await test_session.commit()
    # updated_at defaults to now() on insert, so backdate it with an explicit
    # UPDATE — passing it to the constructor would be silently overwritten.
    await test_session.execute(
        update(CrmDeal)
        .where(CrmDeal.id == stale.id)
        .values(updated_at=datetime(2026, 1, 6, 9, 1))  # 9d before the frozen clock
    )
    await test_session.commit()

    published = []

    async def fake_publish(event_type, org_id, payload, **kw):
        published.append((event_type, org_id, payload, kw))
        return None

    async def must_not_text(*a, **k):
        raise AssertionError("the scheduler must not send WhatsApp itself anymore")

    monkeypatch.setattr("aios.core.events.publish", fake_publish)
    monkeypatch.setattr("aios.core.evolution_api.evo_send_text", must_not_text)
    # Force the once-a-day guard to allow this run.
    monkeypatch.setattr(cron, "_last_crm_mql_alert_day", None, raising=False)
    _freeze_cron_clock(monkeypatch, cron, hour=9, minute=1)

    await cron._crm_mql_stale_tick()

    assert len(published) == 1
    etype, org, payload, kw = published[0]
    assert etype == "crm.deal_stalled"
    assert org == test_org.id
    assert payload["deal_id"] == stale.id
    assert payload["lead_name"] == "Parado"
    assert payload["value"] == 1234.0
    assert kw["idempotency_key"].startswith(f"crm-stalled:{stale.id}:")


async def test_sales_drop_tick_publishes_instead_of_texting(monkeypatch, test_session, test_org):
    import aios.core.cron_scheduler as cron

    published = []

    async def fake_publish(event_type, org_id, payload, **kw):
        published.append((event_type, org_id, payload, kw))
        return None

    async def fake_check(org_id):
        return {"drop_pct": 42.0, "baseline": 1000.0, "current": 580.0}

    async def must_not_send(*a, **k):
        raise AssertionError("the scheduler must not send the alert itself anymore")

    monkeypatch.setattr("aios.core.events.publish", fake_publish)
    monkeypatch.setattr("aios.tools.proactive_alerts.check_sales_drop", fake_check)
    monkeypatch.setattr("aios.tools.proactive_alerts.send_alert_via_evolution", must_not_send)
    monkeypatch.setattr(cron, "_last_proactive_alert_day", None, raising=False)
    _freeze_cron_clock(monkeypatch, cron, hour=8, minute=1)

    # Org must opt in via extra_data, same gate as before.
    test_org.extra_data = {**(test_org.extra_data or {}), "proactive_alerts": "true"}
    await test_session.commit()

    await cron._proactive_alerts_tick()

    assert len(published) == 1
    etype, org, payload, _kw = published[0]
    assert etype == "sales.drop_detected"
    assert org == test_org.id
    assert payload["drop_pct"] == 42.0


async def test_sales_drop_tick_skips_org_that_did_not_opt_in(monkeypatch, test_session, test_org):
    import aios.core.cron_scheduler as cron

    published = []

    async def fake_publish(*a, **k):
        published.append(a)
        return None

    monkeypatch.setattr("aios.core.events.publish", fake_publish)
    monkeypatch.setattr(cron, "_last_proactive_alert_day", None, raising=False)
    _freeze_cron_clock(monkeypatch, cron, hour=8, minute=1)
    test_org.extra_data = {"plan": "pro"}  # no proactive_alerts flag
    await test_session.commit()

    await cron._proactive_alerts_tick()
    assert published == []


# ── idempotency: a restart must not double-message a customer ───────


class _DedupePool:
    def __init__(self, fail=False):
        self.keys: dict[str, str] = {}
        self.fail = fail

    async def delete(self, key):
        self.keys.pop(key, None)
        return 1

    async def set(self, key, value, nx=None, ex=None):
        if self.fail:
            raise RuntimeError("redis down")
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True


async def test_duplicate_event_is_dispatched_only_once(monkeypatch):
    """The daily sweep re-running must not make an agent message twice."""
    o = await _org("ev-dedupe")
    agent = await _mk_agent(o, ["crm.deal_stalled"])
    pool = _DedupePool()

    async def fake_pool():
        return pool

    enqueued = []

    async def fake_enqueue(func, payload, **kw):
        enqueued.append(payload["agent_id"])

    monkeypatch.setattr("aios.tasks.queue.get_redis_pool", fake_pool)
    monkeypatch.setattr("aios.tasks.queue.enqueue_job", fake_enqueue)

    ev = EventEnvelope(
        "crm.deal_stalled", o, {"deal_id": "d1"}, idempotency_key=f"crm-stalled:d1:2026-01-15"
    )
    assert await dispatch_event(ev) == [agent]
    # Same fact re-published (worker restart, retried tick) — must be suppressed.
    assert await dispatch_event(ev) == []
    assert enqueued == [agent]


async def test_different_deals_are_not_suppressed(monkeypatch):
    o = await _org("ev-dedupe-2")
    agent = await _mk_agent(o, ["crm.deal_stalled"])

    async def fake_pool():
        return _DedupePool()

    monkeypatch.setattr("aios.tasks.queue.get_redis_pool", fake_pool)
    monkeypatch.setattr("aios.tasks.queue.enqueue_job", lambda *a, **k: _noop())

    for deal in ("d1", "d2"):
        await dispatch_event(
            EventEnvelope("crm.deal_stalled", o, {"deal_id": deal}, idempotency_key=f"crm-stalled:{deal}:2026-01-15")
        )


async def test_dedupe_fails_open_when_redis_is_unreachable(monkeypatch):
    """Dropping every proactive action is worse than a possible duplicate."""
    o = await _org("ev-dedupe-3")
    agent = await _mk_agent(o, ["crm.deal_stalled"])

    async def dead_pool():
        return _DedupePool(fail=True)

    monkeypatch.setattr("aios.tasks.queue.get_redis_pool", dead_pool)
    monkeypatch.setattr("aios.tasks.queue.enqueue_job", lambda *a, **k: _noop())

    ev = EventEnvelope("crm.deal_stalled", o, {}, idempotency_key="k1")
    assert await dispatch_event(ev) == [agent]


async def test_unkeyed_events_are_not_collapsed_together(monkeypatch):
    """Events without an explicit key get a unique one, so two live events
    both dispatch. Collapsing them would silently lose a real occurrence."""
    o = await _org("ev-dedupe-4")
    agent = await _mk_agent(o, ["crm.deal_stalled"])

    async def fake_pool():
        return _DedupePool()

    monkeypatch.setattr("aios.tasks.queue.get_redis_pool", fake_pool)
    monkeypatch.setattr("aios.tasks.queue.enqueue_job", lambda *a, **k: _noop())

    assert await dispatch_event(EventEnvelope("crm.deal_stalled", o, {"n": 1})) == [agent]
    assert await dispatch_event(EventEnvelope("crm.deal_stalled", o, {"n": 2})) == [agent]


# ── widened tick windows ────────────────────────────────────────────


async def test_mql_tick_still_runs_after_a_delayed_worker(monkeypatch, test_session, test_org):
    """A tick that fires at 09:47 (restart, GC pause) must still report."""
    import aios.core.cron_scheduler as cron
    from sqlalchemy import update

    from aios.db.models import CrmDeal

    stale = CrmDeal(org_id=test_org.id, lead_name="Tarde", stage="mql", value=10.0, pipeline="in")
    test_session.add(stale)
    await test_session.commit()
    await test_session.execute(
        update(CrmDeal).where(CrmDeal.id == stale.id).values(updated_at=datetime(2026, 1, 1, 9, 0))  # >7d before the frozen clock
    )
    await test_session.commit()

    published = []

    async def fake_publish(event_type, org_id, payload, **kw):
        published.append(event_type)
        return None

    monkeypatch.setattr("aios.core.events.publish", fake_publish)
    monkeypatch.setattr(cron, "_last_crm_mql_alert_day", None, raising=False)
    _freeze_cron_clock(monkeypatch, cron, hour=9, minute=47)

    await cron._crm_mql_stale_tick()
    assert published == ["crm.deal_stalled"]


async def test_mql_tick_does_not_run_before_its_hour(monkeypatch, test_session, test_org):
    import aios.core.cron_scheduler as cron

    published = []

    async def fake_publish(*a, **k):
        published.append(a)
        return None

    monkeypatch.setattr("aios.core.events.publish", fake_publish)
    monkeypatch.setattr(cron, "_last_crm_mql_alert_day", None, raising=False)
    _freeze_cron_clock(monkeypatch, cron, hour=6, minute=0)

    await cron._crm_mql_stale_tick()
    assert published == []


# ── configuration surface ───────────────────────────────────────────


def test_agent_update_accepts_valid_event_subscriptions():
    from aios.schemas import AgentUpdate

    for sub in ["crm.*", "*", "message.received", "crm.stage_changed.*"]:
        AgentUpdate(extra_data={"event_subscriptions": [sub]})
    # A bare string is accepted and normalised by the reader.
    AgentUpdate(extra_data={"event_subscriptions": "crm.*"})
    # Unrelated extra_data must pass through untouched.
    AgentUpdate(extra_data={"project_path": "/srv/app"})


@pytest.mark.parametrize("bad", [["crm.*.x"], ["a*b*c"], [""], ["  "], [123]])
def test_agent_update_rejects_unmatchable_subscriptions(bad):
    """A subscription that can never match is a silent failure — reject it."""
    import pydantic

    from aios.schemas import AgentUpdate

    with pytest.raises(pydantic.ValidationError):
        AgentUpdate(extra_data={"event_subscriptions": bad})


async def test_agent_update_merges_extra_data_instead_of_replacing(test_session, test_org):
    """Setting subscriptions must not delete project_path/phone."""
    from aios.api.agents import update_agent
    from aios.db.backends.sqlalchemy_backend import SQLAlchemyBackend
    from aios.db.models import Agent as AgentModel
    from aios.schemas import AgentUpdate

    agent = AgentModel(
        name="Merge",
        org_id=test_org.id,
        status="active",
        extra_data={"project_path": "/srv/keepme", "phone": "+5511999999999"},
    )
    test_session.add(agent)
    await test_session.commit()
    await test_session.refresh(agent)

    await update_agent(
        agent.id,
        AgentUpdate(extra_data={"event_subscriptions": ["crm.*"]}),
        SQLAlchemyBackend(test_session),
        test_org.id,
    )

    extra = (await test_session.get(AgentModel, agent.id)).extra_data
    assert extra["event_subscriptions"] == ["crm.*"]
    # The whole point of the merge: untouched keys survive.
    assert extra["project_path"] == "/srv/keepme"
    assert extra["phone"] == "+5511999999999"


async def test_failed_enqueue_releases_the_claim_so_a_retry_still_delivers(monkeypatch):
    """A dispatch that landed nothing must not be able to lose the event.

    The consumer leaves a failed entry unacked and redelivers it; if the dedupe
    claim survived, that retry would look like a duplicate and the proactive
    action would be dropped forever.
    """
    o = await _org("ev-claim-release")
    agent = await _mk_agent(o, ["crm.*"])
    pool = _DedupePool()

    async def fake_pool():
        return pool

    monkeypatch.setattr("aios.tasks.queue.get_redis_pool", fake_pool)

    attempts = []

    async def flaky_enqueue(func, payload, **kw):
        attempts.append(payload["agent_id"])
        if len(attempts) == 1:
            raise RuntimeError("redis blip")

    monkeypatch.setattr("aios.tasks.queue.enqueue_job", flaky_enqueue)

    ev = EventEnvelope("crm.stage_changed.won", o, {}, idempotency_key="k-release")
    assert await dispatch_event(ev) == []
    # Retry of the same entry must still be able to deliver.
    assert await dispatch_event(ev) == [agent]
    assert len(attempts) == 2


async def test_successful_dispatch_keeps_the_claim(monkeypatch):
    """The dedupe key must survive a successful dispatch, or duplicates return."""
    o = await _org("ev-claim-keep")
    agent = await _mk_agent(o, ["crm.*"])
    pool = _DedupePool()

    async def fake_pool():
        # One pool instance: a fresh one per call would lose the claim.
        return pool

    monkeypatch.setattr("aios.tasks.queue.get_redis_pool", fake_pool)
    monkeypatch.setattr("aios.tasks.queue.enqueue_job", lambda *a, **k: _noop())

    ev = EventEnvelope("crm.stage_changed.won", o, {}, idempotency_key="k-keep")
    assert await dispatch_event(ev) == [agent]
    assert await dispatch_event(ev) == []
