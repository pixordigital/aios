"""Live agent-activity event bridge for the agent canvas.

Turns agent execution into org-scoped events on a WebSocket, so the canvas can
show which agent is running, what it streamed, and who handed work to whom.

Two delivery problems, two mechanisms:

1. *In-process* — a local queue drained by one pump task. Lifecycle events come
   from the synchronous hook registry (``aios.core.hooks``), which is why
   ``ws_manager.broadcast`` only enqueues.
2. *Cross-process* — most agent runs do NOT happen in the web process. Channel
   webhooks, cron jobs and workflows dispatch to the ARQ worker, so their events
   are emitted in a different process than the socket held by the browser. A
   redis pub/sub bridge is the only way those are ever visible.

Redis is optional. When it is unavailable the bridge reports
``CROSS_PROCESS = False`` and the canvas shows a banner saying so, rather than
quietly showing an incomplete picture.

Deliberately not built: persistence/replay. ``aios.core.tracing.get_trace`` is
the path if that is ever wanted.
"""

import asyncio
import json
import logging
from typing import Any

from aios.core.hooks import HookContext, HookPoint, hooks
from aios.core.ws_manager import ws_manager

logger = logging.getLogger(__name__)

CHANNEL = "aios:agent_events"

# Bounded so a redis that accepts the socket but never answers cannot stall
# startup. arq's own create_pool retries 5x with a 1s delay and 1s connect
# timeout (~11s worst case), so this is a real bound, not a formality.
REDIS_CONNECT_TIMEOUT = 2.0

_publish_pool: Any = None
_subscriber: Any = None
_pump_task: asyncio.Task | None = None
_subscriber_task: asyncio.Task | None = None

# True only when events raised in another process can reach this one.
CROSS_PROCESS = False

_hooks_registered = False


# ── event construction ─────────────────────────────────────────────


def emit_stream_event(agent: Any, event: dict, run_id: str) -> dict:
    """Tag a stream event with its agent identity and publish it.

    Synchronous on purpose: called from the async generator in
    ``AgentRuntime.run_stream`` and wired to sync hooks. Returns the tagged
    event so the caller can keep yielding exactly what it produced.
    """
    tagged = dict(event)
    tagged.setdefault("agent_id", getattr(agent, "id", "") or "")
    tagged.setdefault("org_id", getattr(agent, "org_id", "") or "")
    tagged.setdefault("run_id", run_id)
    ws_manager.broadcast(tagged)
    return tagged


def _lifecycle_event(kind: str, ctx: HookContext) -> dict:
    return {
        "type": kind,
        "agent_id": ctx.agent_id or "",
        "org_id": ctx.org_id or ctx.data.get("org_id", "") or "",
        "conversation_id": ctx.conversation_id or ctx.data.get("conversation_id", "") or "",
    }


def _on_agent_start(ctx: HookContext) -> None:
    ws_manager.broadcast(_lifecycle_event("node_start", ctx))


def _on_agent_end(ctx: HookContext) -> None:
    ws_manager.broadcast(_lifecycle_event("node_end", ctx))


def _on_agent_error(ctx: HookContext) -> None:
    ev = _lifecycle_event("node_error", ctx)
    ev["error"] = (ctx.data.get("error") or "")[:500]
    ws_manager.broadcast(ev)


def emit_trial_event(agent: Any, trial: int, max_trials: int, conversation_id: str) -> dict:
    """Publish an autonomous trial boundary (see AutonomousAgent.run)."""
    tagged = {
        "type": "trial_start",
        "agent_id": getattr(agent, "id", "") or "",
        "org_id": getattr(agent, "org_id", "") or "",
        "conversation_id": conversation_id or "",
        "trial": trial,
        "max_trials": max_trials,
    }
    ws_manager.broadcast(tagged)
    return tagged


# ── delivery ──────────────────────────────────────────────────────


async def _pump() -> None:
    """Drain the local queue: publish to redis, or deliver in-process."""
    while True:
        data = await ws_manager.queue.get()
        global CROSS_PROCESS, _publish_pool
        if CROSS_PROCESS and _publish_pool is not None:
            try:
                await _publish_pool.publish(CHANNEL, json.dumps(data))
                continue
            except Exception as e:
                # Redis died mid-run. Fall back to local delivery rather than
                # going silent — a stale CROSS_PROCESS=True would leave the
                # canvas blank with no explanation.
                logger.warning("agent canvas: publish failed (%s), reverting to in-process", e)
                CROSS_PROCESS = False
                _publish_pool = None
        try:
            await ws_manager._deliver_local(data)
        except Exception:
            logger.debug("agent canvas: local deliver failed", exc_info=True)


async def _subscribe() -> None:
    """Receive events published by other processes and fan them out locally."""
    global CROSS_PROCESS
    pubsub = _subscriber.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe(CHANNEL)
    logger.info("agent canvas: subscribed to %s", CHANNEL)
    try:
        async for message in pubsub.listen():
            if message is None or message.get("type") != "message":
                continue
            raw = message.get("data")
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", "replace")
            try:
                data = json.loads(raw)
            except Exception:
                continue
            try:
                await ws_manager._deliver_local(data)
            except Exception:
                logger.debug("agent canvas: relay deliver failed", exc_info=True)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("agent canvas: subscriber stopped (%s)", e)
        CROSS_PROCESS = False


# ── lifecycle ─────────────────────────────────────────────────────


def register_hooks() -> None:
    """Wire the synchronous lifecycle hooks. Idempotent per process.

    lifespan can be entered more than once in a process (test clients, reload),
    and a second registration would publish every lifecycle event twice.
    """
    global _hooks_registered
    if _hooks_registered:
        return
    hooks.register(HookPoint.AGENT_START, _on_agent_start)
    hooks.register(HookPoint.AGENT_END, _on_agent_end)
    hooks.register(HookPoint.AGENT_ERROR, _on_agent_error)
    _hooks_registered = True


async def init() -> bool:
    """Start the pump and, if redis is reachable, the cross-process bridge.

    Never raises and never blocks startup for long: the canvas is a dashboard,
    not a health dependency (``/health/ready`` already gates on redis).
    """
    global _publish_pool, _subscriber, _pump_task, _subscriber_task, CROSS_PROCESS

    register_hooks()

    if _pump_task is None or _pump_task.done():
        _pump_task = asyncio.create_task(_pump())

    try:
        import os

        from aios.config import settings
        from aios.tasks.queue import get_redis_pool

        url = settings.redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        _publish_pool = await asyncio.wait_for(get_redis_pool(), timeout=REDIS_CONNECT_TIMEOUT)
    except Exception as e:
        _publish_pool = None
        CROSS_PROCESS = False
        logger.warning(
            "agent canvas: redis bridge unavailable (%s) — channel/cron agent runs "
            "will not appear on the canvas", e,
        )
        return False

    # Dedicated connection for the subscription. A redis-py PubSub holds its
    # connection for its whole lifetime, so it must not squat on the shared ARQ
    # pool that job dispatch uses.
    try:
        from redis.asyncio import Redis

        from aios.tasks.queue import _parse_redis

        rs = _parse_redis(url)  # same SASL/TLS parsing as the ARQ pool
        _subscriber = Redis(
            host=rs.host, port=rs.port, db=rs.database, username=rs.username,
            password=rs.password, ssl=rs.ssl, socket_connect_timeout=1,
        )
        _subscriber_task = asyncio.create_task(_subscribe())
        CROSS_PROCESS = True
        logger.info("agent canvas: cross-process bridge up (%s:%s/%s)", rs.host, rs.port, rs.database)
        return True
    except Exception as e:
        _subscriber = None
        CROSS_PROCESS = False
        logger.warning("agent canvas: subscriber unavailable (%s) — in-process events only", e)
        return False


async def shutdown() -> None:
    """Cancel the pump, then the subscriber.

    Order matters: the subscriber holds a dedicated redis connection, so it
    must be closed before the shared pool is closed by the lifespan.
    """
    global _pump_task, _subscriber_task, _subscriber, _publish_pool, CROSS_PROCESS

    for task in (_subscriber_task, _pump_task):
        if task is not None and not task.done():
            task.cancel()
    for task in (_subscriber_task, _pump_task):
        if task is not None:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
    _subscriber_task = None
    _pump_task = None

    if _subscriber is not None:
        try:
            await _subscriber.aclose()
        except Exception:
            logger.debug("agent canvas: subscriber close failed", exc_info=True)
        _subscriber = None
    _publish_pool = None
    CROSS_PROCESS = False
