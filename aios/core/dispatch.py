"""Inbound message dispatch — routes incoming messages to ARQ worker.

Webhook handlers publish InboundEvent here. This module enqueues
an ARQ job that the worker picks up to process the message asynchronously.
"""

import json
import logging

logger = logging.getLogger(__name__)


async def dispatch_inbound(
    channel_type: str,
    channel_connection_id: str,
    conversation_id: str,
    text: str,
    user_id: str = "",
    extra_data: dict | None = None,
):
    """Enqueue inbound message for async processing by ARQ worker.

    Called by webhook handlers after receiving a message.
    Returns immediately — worker processes in background.
    """
    from aios.tasks.queue import get_redis_pool

    pool = await get_redis_pool()
    await pool.enqueue_job(
        "aios.tasks.jobs.process_inbound",
        channel_type,
        channel_connection_id,
        conversation_id,
        text,
        user_id,
        json.dumps(extra_data or {}),
    )
    logger.info("Dispatched inbound %s/%s to worker", channel_type, conversation_id[:8])
