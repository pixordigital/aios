"""Redis connection pool + ARQ job enqueue.

Reads REDIS_URL from env or settings.redis_url.
"""

import logging
import os
from typing import Optional
from urllib.parse import urlparse

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from aios.config import settings

logger = logging.getLogger(__name__)

_redis_pool: Optional[ArqRedis] = None


def _parse_redis(url: str) -> RedisSettings:
    """Parse redis:// URL into RedisSettings."""
    parsed = urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or "0"),
        password=parsed.password or None,
    )


async def get_redis_pool() -> ArqRedis:
    """Return shared ARQ Redis pool — created on first call."""
    global _redis_pool
    if _redis_pool is None:
        url = settings.redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        redis_settings = _parse_redis(url)
        _redis_pool = await create_pool(redis_settings)
        logger.info("Redis pool connected to %s:%d", redis_settings.host, redis_settings.port)
    return _redis_pool


async def enqueue_job(func_name: str, *args, priority: str = "normal", **kwargs):
    """Enqueue async job via ARQ. priority: high|normal|low -> high uses queue high if available."""
    pool = await get_redis_pool()
    # ARQ priority via queue_name (requires separate worker poll, fallback to normal)
    if priority == "high":
        try:
            await pool.enqueue_job(func_name, *args, _queue_name="high", **kwargs)
            logger.debug("Enqueued high-prio job %s", func_name)
            return
        except TypeError:
            pass  # arq version without _queue_name
    await pool.enqueue_job(func_name, *args, **kwargs)
    logger.debug("Enqueued job %s prio=%s", func_name, priority)


async def enqueue_task(task_name: str, payload: dict):
    """Lightweight task enqueue — falls back to no-op if Redis unavailable."""
    try:
        pool = await get_redis_pool()
        await pool.enqueue_job(task_name, payload)
    except Exception:
        logger.debug("enqueue_task fallback (no redis): %s", task_name)


async def close_pool():
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.close()
        _redis_pool = None
