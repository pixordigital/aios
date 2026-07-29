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


async def enqueue_job(func_name: str, *args, **kwargs):
    """Enqueue async job via ARQ."""
    pool = await get_redis_pool()
    await pool.enqueue_job(func_name, *args, **kwargs)
    logger.debug("Enqueued job %s", func_name)


async def close_pool():
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.close()
        _redis_pool = None
