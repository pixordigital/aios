"""Webhook retry + dead letter queue for channel message processing."""

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAYS = [5, 30, 120]  # seconds: 5s, 30s, 2min
_DLQ_MAX_SIZE = 1000

# In-memory DLQ — Redis-backed when available
_dlq: list[dict] = []


async def process_with_retry(
    func: Callable[..., Coroutine],
    *args,
    channel_type: str = "unknown",
    message_id: str = "",
    **kwargs,
) -> Any:
    """Execute webhook handler with retry. Moves to DLQ after max retries."""
    last_error = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < _MAX_RETRIES:
                delay = _RETRY_DELAYS[attempt]
                logger.warning(
                    "Webhook processing failed (attempt %d/%d) for %s/%s: %s. Retrying in %ds",
                    attempt + 1, _MAX_RETRIES, channel_type, message_id, e, delay,
                )
                import asyncio
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "Webhook processing failed permanently for %s/%s: %s",
                    channel_type, message_id, e,
                )

    # Move to DLQ
    _add_to_dlq(channel_type, message_id, str(last_error), args, kwargs)
    return None


def _add_to_dlq(channel_type: str, message_id: str, error: str, args: tuple, kwargs: dict):
    """Add failed message to dead letter queue."""
    entry = {
        "channel_type": channel_type,
        "message_id": message_id,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "args_summary": str(args)[:500],
        "kwargs_summary": str(kwargs)[:500],
    }
    _dlq.append(entry)
    if len(_dlq) > _DLQ_MAX_SIZE:
        _dlq.pop(0)
    logger.error("DLQ: added %s/%s (size: %d)", channel_type, message_id, len(_dlq))


def get_dlq(limit: int = 50) -> list[dict]:
    """Get recent DLQ entries."""
    return list(reversed(_dlq[-limit:]))


def clear_dlq():
    """Clear DLQ."""
    _dlq.clear()
