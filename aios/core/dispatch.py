"""Inbound message dispatch — routes incoming messages to ARQ worker.

Webhook handlers publish InboundEvent here. This module enqueues
an ARQ job that the worker picks up to process the message asynchronously.
"""

import hashlib
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

    try:
        # Inside the try on purpose: get_redis_pool() used to be called above it,
        # so a Redis outage raised out of dispatch_inbound straight into the
        # webhook handler. Evolution got a 500, retried, gave up, and the DLQ
        # fallback written below never ran.
        pool = await get_redis_pool()
        extra = json.dumps(extra_data or {})
        job_kwargs = {}
        provider_msg_id = ""
        if isinstance(extra_data, dict):
            provider_msg_id = str(
                extra_data.get("msg_id") or extra_data.get("message_id") or ""
            )
        if provider_msg_id:
            key = f"{channel_type}:{channel_connection_id}:{provider_msg_id}".encode()
            job_kwargs["_job_id"] = "inbound:" + hashlib.sha256(key).hexdigest()
        await pool.enqueue_job(
            "aios.tasks.jobs.process_inbound",
            channel_type,
            channel_connection_id,
            conversation_id,
            text,
            user_id,
            extra,
            **job_kwargs,
        )
        logger.info("Dispatched inbound %s/%s to worker", channel_type, conversation_id[:8])
    except Exception as exc:
        # Redis down or queue error — don't lose the message, land in DLQ.
        from aios.core.dead_letter import write_dlq
        await write_dlq(
            direction="inbound",
            channel_type=channel_type,
            job_name="aios.tasks.jobs.process_inbound",
            payload={
                "args": [channel_type, channel_connection_id, conversation_id, text, user_id, json.dumps(extra_data or {})],
                "kwargs": {},
            },
            error=f"enqueue failed: {exc}",
            channel_connection_id=channel_connection_id,
            conversation_id=conversation_id or None,
        )
        logger.exception("dispatch_inbound enqueue failed for %s/%s", channel_type, conversation_id[:8])
