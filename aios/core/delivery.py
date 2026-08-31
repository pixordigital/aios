"""Message delivery — background retry + dead-letter queue.

Wraps channel sends in ARQ jobs with retry and exponential backoff.
Failed messages after max retries land in a DB DLQ table.
"""

import json
import logging

from aios.core.dead_letter import write_dlq
from aios.db.backend import db_session
from aios.db.models import ChannelConnection

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY_S = 5.0


async def deliver_message(
    ctx,
    channel_connection_id: str,
    conversation_id: str,
    text: str,
    extra_data: str = "{}",
    attempt: int = 1,
):
    """Send message via channel. Retries with backoff on failure.

    Called directly (non-streaming) or via ARQ worker.
    """
    from aios.channels.manager import manager as channel_mgr

    try:
        extra = json.loads(extra_data) if isinstance(extra_data, str) else extra_data
    except json.JSONDecodeError:
        extra = {}

    conn = None
    try:
        if text and len(text) > 4096:
            text = text[:4096]
        if channel_connection_id:
            try:
                from aios.core.whatsapp_guard import guard_send

                extra_j = json.loads(extra_data) if isinstance(extra_data, str) else extra_data
                contact = extra_j.get("from_number") or extra_j.get("to") or conversation_id
                window_open = extra_j.get("window_open", True)
                is_template = extra_j.get("is_template", False)
                ok, reason = await guard_send(contact, text, is_template=is_template, window_open=window_open)
                if not ok:
                    logger.warning("Guard block %s: %s", contact, reason)
                    if "opt-out" in reason:
                        return
                    from aios.tasks.queue import get_redis_pool as _pool

                    pool = await _pool()
                    await pool.enqueue_job(
                        "aios.core.delivery.deliver_message",
                        channel_connection_id,
                        conversation_id,
                        text,
                        extra_data,
                        attempt,
                        _defer_seconds=30,
                    )
                    return
            except Exception:
                pass
        async with db_session() as db:
            conn = await db.get(ChannelConnection, channel_connection_id)
            if not conn:
                logger.warning("DLQ: channel %s not found", channel_connection_id)
                return

            # resolve agent/team if needed
            agent_or_team = None
            if conn.agent_id:
                from aios.db.models import Agent
                agent_or_team = await db.get(Agent, conn.agent_id)
            elif conn.team_id:
                from aios.db.models import Team
                from sqlalchemy.orm import selectinload
                agent_or_team = await db.get(Team, conn.team_id, options=[selectinload(Team.agents)])

            from aios.channels.base import OutboundMessage
            msg = OutboundMessage(
                conversation_id=conversation_id,
                text=text,
                channel_connection_id=channel_connection_id,
                extra_data=extra,
            )
            ch = channel_mgr.build(conn, agent_or_team, db)
            result = await ch.send(msg)

            if result is not None:
                logger.info("Message delivered to channel %s", channel_connection_id)
                return

            # send returned None — channel unavailable
            raise ConnectionError("Channel send returned None")

    except Exception as exc:
        logger.warning("Delivery attempt %d/%d failed for channel %s: %s",
                       attempt, _MAX_RETRIES, channel_connection_id, exc)
        if attempt < _MAX_RETRIES:
            # re-enqueue with backoff via ARQ
            from aios.tasks.queue import get_redis_pool
            pool = await get_redis_pool()
            delay = _BASE_DELAY_S * (2 ** (attempt - 1))
            await pool.enqueue_job(
                "aios.core.delivery.deliver_message",
                channel_connection_id,
                conversation_id,
                text,
                extra_data,
                attempt + 1,
                _defer_seconds=delay,
            )
        else:
            # max retries exceeded — DLQ
            await write_dlq(
                direction="outbound",
                channel_type=getattr(conn, "channel_type", ""),
                job_name="aios.core.delivery.deliver_message",
                payload={"args": [channel_connection_id, conversation_id, text, extra_data], "kwargs": {}},
                error=str(exc),
                org_id=getattr(conn, "org_id", None),
                channel_connection_id=channel_connection_id,
                conversation_id=conversation_id,
            )
            logger.error("DLQ: message to channel %s failed after %d attempts",
                         channel_connection_id, _MAX_RETRIES)