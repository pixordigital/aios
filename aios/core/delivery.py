"""Message delivery — background retry + dead-letter queue.

Wraps channel sends in ARQ jobs with retry and exponential backoff.
Failed messages after max retries land in a DB DLQ table.
"""

import json
import logging
import uuid

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

    try:
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
            await _write_dlq(channel_connection_id, conversation_id, text, str(exc))
            logger.error("DLQ: message to channel %s failed after %d attempts",
                         channel_connection_id, _MAX_RETRIES)


async def _write_dlq(channel_id: str, conv_id: str, text: str, error: str):
    """Persist failed message to dead-letter queue."""
    async with db_session() as db:
        from aios.db.models import Artifact
        art = Artifact(
            org_id="dlq",
            conversation_id=conv_id,
            filename=f"dlq_{channel_id}_{uuid.uuid4().hex[:8]}.txt",
            content_type="text/plain",
            size_bytes=len(text),
            storage_path="dlq",
            description=json.dumps({"channel_id": channel_id, "error": error}),
        )
        db.add(art)
        await db.commit()
        logger.info("DLQ entry written for channel %s", channel_id)


async def list_dlq(limit: int = 50) -> list[dict]:
    """List dead-letter queue entries."""
    from aios.core.storage import list_artifacts
    async with db_session() as db:
        return await list_artifacts(db, org_id="dlq", limit=limit)


async def retry_dlq(artifact_id: str):
    """Re-enqueue a DLQ'd message for delivery."""
    from aios.core.storage import get_artifact_content, list_artifacts
    async with db_session() as db:
        arts = await list_artifacts(db, org_id="dlq", limit=1)
        art = next((a for a in arts if a["id"] == artifact_id), None)
        if not art:
            return
        desc = json.loads(art["description"])
        content = await get_artifact_content(artifact_id, db)
        text = content.decode("utf-8") if content else ""

    from aios.tasks.queue import get_redis_pool
    pool = await get_redis_pool()
    await pool.enqueue_job(
        "aios.core.delivery.deliver_message",
        desc.get("channel_id", ""),
        art["conversation_id"],
        text,
        "{}",
        1,
    )