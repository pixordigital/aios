"""Durable org-scoped event bus for proactive agents.

Problem this solves: agents were reactive only — they ran when a message
arrived. Proactive behaviour existed as *polling* (``aios.core.cron_scheduler``
ticked every 60s and sent WhatsApp directly), which meant the alerting logic
lived in the scheduler, was invisible to agents, could not be governed, and
could not be reasoned about per-org.

The fix is one indirection: producers ``publish`` an event, and a single
dispatcher decides which agents react. No agent wakes up on a timer; agents
wake up because something happened.

Redis Streams, not pub/sub: ``agent_events`` already bridges live activity with
pubsub but is deliberately replay-less (its own docstring says so). Proactive
work must survive a worker restart, otherwise a `deal.stage_changed` published
during a deploy is lost and nobody follows up. Streams give us a pending-entry
list, consumer groups, and XACK/XAUTOCLAIM for free.

Deliberately not built: an event DSL, a rules engine, or an event sourcing
rewrite of existing tables. Publishers emit a fixed envelope; subscriptions live
in ``Agent.extra_data["event_subscriptions"]``. Grow it when a second consumer
pattern actually shows up.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import select

from aios.db.engine import async_session
from aios.db.models import Agent

logger = logging.getLogger(__name__)

# Single stream for all orgs. Isolation is enforced at dispatch (an event only
# reaches agents in the event's org), not by one stream per org — one stream per
# org means one consumer group per org and a consumer that must join thousands
# of groups. Org stays in the payload where the filter is a single index scan.
STREAM = "aios:events"

GROUP = "aios-dispatchers"

# Namespace for "already dispatched" markers. Separate keyspace from the stream
# so trimming the stream never deletes dedupe state.
DEDUPE_PREFIX = "aios:evt:idem:"

# Bounded so a stalled consumer cannot park an event forever and silently hold
# org memory. Consumers re-claim after this via XAUTOCLAIM.
CLAIM_IDLE_MS = 5 * 60 * 1000

# Redis is optional in dev; a down bus must not break inbound messaging.
PUBLISH_TIMEOUT = 2.0


class EventEnvelope:
    """Canonical event shape.

    ``event_type`` is dotted and namespaced (``crm.stage_changed``) so a
    subscription can be exact or prefix-wildcarded without ambiguity.
    """

    __slots__ = ("event_id", "event_type", "org_id", "actor_id", "payload", "ts", "idempotency_key")

    def __init__(
        self,
        event_type: str,
        org_id: str,
        payload: dict | None = None,
        actor_id: str = "",
        idempotency_key: str = "",
        event_id: str = "",
    ):
        # No-op events are almost always a bug upstream (an empty dict from a
        # failed branch), and they wake every wildcard subscriber.
        if not event_type or not org_id:
            raise ValueError("event_type and org_id are required")
        self.event_id = event_id or str(uuid.uuid4())
        self.event_type = event_type
        self.org_id = org_id
        self.actor_id = actor_id or ""
        self.payload = payload or {}
        self.ts = datetime.now(timezone.utc).isoformat()
        # Keyed on the semantic identity of the fact, not the delivery, so a
        # retried publish or a duplicate webhook does not double-notify.
        self.idempotency_key = idempotency_key or self.event_id

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "org_id": self.org_id,
            "actor_id": self.actor_id,
            "payload": self.payload,
            "ts": self.ts,
            "idempotency_key": self.idempotency_key,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EventEnvelope":
        """Parse an event leniently — a malformed entry must not raise.

        Validation lives in ``__init__`` for producers, but this parser runs on
        whatever is sitting in the stream. Raising here would bypass the
        consumer's malformed-event guard and push the entry onto the
        leave-unacked path, where it is redelivered forever instead of dropped.
        The caller (``_handle``) is what decides an event is unusable.
        """
        ev = cls.__new__(cls)
        ev.event_type = data.get("event_type", "") or ""
        ev.org_id = data.get("org_id", "") or ""
        ev.payload = data.get("payload") or {}
        ev.actor_id = data.get("actor_id", "") or ""
        ev.idempotency_key = data.get("idempotency_key", "") or ""
        ev.event_id = data.get("event_id", "") or ""
        ev.ts = data.get("ts", "") or ""
        return ev

    def matches(self, subscription: str) -> bool:
        return ev_type_matches(self.event_type, subscription)


def subscriptions_for(agent: Agent) -> list[str]:
    """Read an agent's event subscriptions.

    Lives in ``extra_data`` rather than a new table/column: it is config that
    ships with the agent definition, and a JSON list needs no migration and no
    join to inspect in the dashboard.
    """
    raw = (agent.extra_data or {}).get("event_subscriptions") or []
    if isinstance(raw, str):
        raw = [raw]
    return [s for s in (str(x).strip() for x in raw) if s]


def _encode(ev: EventEnvelope) -> dict[str, Any]:
    # Redis stream fields must be flat str->str; payload is the only nested part
    # and is JSON-serialised here so the consumer never needs a schema.
    return {
        "event_id": str(ev.event_id),
        "event_type": str(ev.event_type),
        "org_id": str(ev.org_id),
        "actor_id": str(ev.actor_id),
        "payload": json.dumps(ev.payload, default=str),
        "ts": str(ev.ts),
        "idempotency_key": str(ev.idempotency_key),
    }


async def publish(
    event_type: str,
    org_id: str,
    payload: dict | None = None,
    *,
    actor_id: str = "",
    idempotency_key: str = "",
) -> EventEnvelope | None:
    """Append an event to the stream. Returns the envelope, or None if Redis is down.

    Never raises: a producer failing because the bus is unavailable must not
    take down the request or message that produced the event. The consequence is
    a lost proactive trigger, which is why the failure is logged at error level
    rather than swallowed.
    """
    ev = EventEnvelope(
        event_type=event_type,
        org_id=org_id,
        payload=payload,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
    )
    try:
        from aios.tasks.queue import get_redis_pool

        pool = await get_redis_pool()
        # redis-py's stub types fields as an invariant generic; a flat str->str
        # mapping is correct at runtime and satisfies every real version.
        await pool.xadd(STREAM, _encode(ev), maxlen=100_000, approximate=True)  # type: ignore[arg-type]
    except Exception:
        logger.error("event publish failed for %s org=%s", event_type, org_id, exc_info=True)
        return None
    logger.debug("published %s org=%s", event_type, org_id)
    return ev


async def publish_many(event_type: str, org_ids: Iterable[str], payload_for) -> int:
    """Publish one event per org with an org-specific payload.

    ``payload_for`` is a callable so per-org payloads are built only when Redis
    accepted the batch, and so no org's data leaks into another's event.
    """
    n = 0
    for org_id in org_ids:
        try:
            payload = payload_for(org_id)
        except Exception:
            logger.exception("event payload build failed for %s org=%s", event_type, org_id)
            continue
        if payload is None:
            continue
        if await publish(event_type, org_id, payload):
            n += 1
    return n


async def ensure_group(pool) -> None:
    """Create the consumer group if absent. BUSYGROUP means someone won the race."""
    try:
        await pool.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def matching_agents(org_id: str, event_type: str) -> list[Agent]:
    """Active agents in the org subscribed to this event type.

    Loads all active agents for the org and filters in Python: subscription
    matching is wildcard logic that SQL cannot express without a bespoke
    operator, and the per-org active agent count is small. Org filter is in
    SQL, which is the isolation boundary that matters.
    """
    async with async_session() as sess:
        agents = (
            await sess.execute(select(Agent).where(Agent.org_id == org_id, Agent.status == "active"))
        ).scalars().all()
    return [a for a in agents if any(ev_type_matches(event_type, s) for s in subscriptions_for(a))]


def ev_type_matches(event_type: str, subscription: str) -> bool:
    # A typeless event is malformed. It must match nothing — least of all "*",
    # which would fan it out to every subscriber in the org.
    if not event_type:
        return False
    sub = (subscription or "").strip()
    if not sub:
        return False
    if sub == "*" or sub == event_type:
        return True
    if sub.endswith("*"):
        return event_type.startswith(sub[:-1])
    return False


async def claim_idempotency(ev: EventEnvelope, ttl: int = 86400) -> bool:
    """True if this fact has not been dispatched before.

    Guards the damaging case: a restart re-running a daily sweep would otherwise
    make an agent send the same WhatsApp to the same customer twice. TTL rather
    than permanent so a legitimately repeated fact (a deal stalled again next
    week) still dispatches.

    Fails *open* on Redis trouble. The alternative — treating an unreachable
    key store as "already sent" — silently drops every proactive action, which
    is the failure this whole system exists to prevent.
    """
    return await _claim(ev.idempotency_key, ttl)


async def _claim(idempotency_key: str, ttl: int = 86400) -> bool:
    key = f"{DEDUPE_PREFIX}{idempotency_key}"
    try:
        from aios.tasks.queue import get_redis_pool

        pool = await get_redis_pool()
        return bool(await pool.set(key, "1", nx=True, ex=ttl))
    except Exception:
        logger.warning("idempotency check failed for %s, allowing dispatch", idempotency_key)
        return True


async def release_idempotency(ev: EventEnvelope) -> None:
    """Undo a claim when nothing was actually delivered."""
    await _release(ev.idempotency_key)


async def _release(idempotency_key: str) -> None:
    try:
        from aios.tasks.queue import get_redis_pool

        pool = await get_redis_pool()
        await pool.delete(f"{DEDUPE_PREFIX}{idempotency_key}")
    except Exception:
        logger.debug("could not release idempotency key %s", idempotency_key, exc_info=True)


async def dispatch_event(ev: EventEnvelope) -> list[str]:
    """Resolve subscribers and enqueue an autonomous run for each.

    Returns the agent ids dispatched to, so callers/tests can assert routing
    without reading ARQ internals.

    Claims are per agent, not per event. Claiming once for the whole event
    meant a partial failure — A enqueued, B's enqueue raised — kept the claim
    for both, so B was never retried while the consumer considered the event
    delivered. Per-agent claims keep the duplicate protection (two racing
    consumers still cannot double-dispatch the same agent) and let a retry
    deliver exactly the subscribers that missed out.
    """
    agents = await matching_agents(ev.org_id, ev.event_type)
    if not agents:
        logger.debug("no subscribers for %s org=%s", ev.event_type, ev.org_id)
        return []

    from aios.tasks.queue import enqueue_job

    dispatched: list[str] = []
    for agent in agents:
        key = f"{ev.idempotency_key}:{agent.id}" if ev.idempotency_key else ""
        if key and not await _claim(key):
            logger.info(
                "duplicate %s suppressed agent=%s key=%s",
                ev.event_type, agent.id, ev.idempotency_key,
            )
            continue
        try:
            await enqueue_job(
                "aios.tasks.jobs.proactive_event_job",
                {
                    "event": ev.to_dict(),
                    "agent_id": agent.id,
                    "org_id": ev.org_id,
                },
            )
            dispatched.append(agent.id)
        except Exception:
            # One undeliverable subscriber must not block the others, and its
            # claim must not outlive the failure: the consumer leaves this
            # entry unacked and retries it, and a stale claim would make that
            # retry look like a duplicate and drop this agent for good.
            logger.exception("dispatch failed agent=%s event=%s", agent.id, ev.event_type)
            if key:
                await _release(key)

    logger.info(
        "dispatched %s to %d agent(s) org=%s", ev.event_type, len(dispatched), ev.org_id
    )
    return dispatched


async def _handle(fields: dict[str, str]) -> None:
    """Turn one stream entry into a dispatch.

    The envelope lives in the stream's own fields; only ``payload`` is nested
    JSON. Decoding ``payload`` alone and treating it as the envelope would drop
    every real event, because the business payload has no event_type/org_id.
    """
    raw = fields.get("payload") or "{}"
    try:
        payload = json.loads(raw)
    except Exception:
        logger.error("event payload not JSON, dropping: %.200s", raw)
        return
    ev = EventEnvelope.from_dict({**fields, "payload": payload})
    if not ev.event_type or not ev.org_id:
        logger.error("event missing type/org, dropping: %.200s", raw)
        return
    await dispatch_event(ev)


async def consume_once(pool=None, block_ms: int = 1000, count: int = 10) -> int:
    """Read one batch and dispatch it. Returns the number of events handled.

    Blocking read so the worker loop is idle-cheap; ARQ runs this on a cron so
    the process spends nothing while no events exist. Events claimed but not
    acked (worker died mid-dispatch) are re-delivered after ``CLAIM_IDLE_MS``.
    """
    from aios.tasks.queue import get_redis_pool

    pool = pool or await get_redis_pool()
    await ensure_group(pool)

    handled = 0

    # Reclaim entries abandoned by a crashed consumer before reading new ones.
    # Reclaimed events count toward ``handled``: they are real dispatches, and
    # excluding them made a batch of them report 0 — indistinguishable from an
    # idle bus to anything watching the job result.
    try:
        pending = await pool.xautoclaim(STREAM, GROUP, consumername="dispatcher", min_idle_time=CLAIM_IDLE_MS, count=count, start_id="0-0")
        # redis-py returns (next_id, [(id, fields), ...]).
        stale = pending[1] if isinstance(pending, (list, tuple)) and len(pending) > 1 else []
        for msg_id, fields in stale:
            try:
                await _handle(fields)
            except Exception:
                # Same rule as below: stay unacked so it is retried.
                logger.exception("reclaimed event %s failed, leaving for retry", msg_id)
                continue
            await pool.xack(STREAM, GROUP, msg_id)
            handled += 1
    except Exception:
        logger.debug("xautoclaim failed (older redis?)", exc_info=True)

    try:
        entries = await pool.xreadgroup(
            GROUP, "dispatcher", {STREAM: ">"}, count=count, block=block_ms
        )
    except Exception:
        logger.exception("event read failed")
        return handled

    for _stream, msgs in entries or []:
        for msg_id, fields in msgs:
            try:
                await _handle(fields)
            except Exception:
                # Leave unacked: XAUTOCLAIM will redeliver. Poison events are
                # bounded by the maxlen trim, not by infinite redelivery.
                logger.exception("event %s dispatch failed, leaving for reclaim", msg_id)
                continue
            await pool.xack(STREAM, GROUP, msg_id)
            handled += 1
    return handled


async def run_consumer(stop: asyncio.Event | None = None) -> None:
    """Consumer loop for the ARQ worker. Runs until ``stop`` is set or cancelled."""
    from aios.tasks.queue import get_redis_pool

    logger.info("event consumer started stream=%s group=%s", STREAM, GROUP)
    pool = await get_redis_pool()
    await ensure_group(pool)
    while stop is None or not stop.is_set():
        try:
            await consume_once(pool)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Back off on a failing bus instead of hot-looping on the error.
            logger.exception("event consumer iteration failed")
            await asyncio.sleep(1)