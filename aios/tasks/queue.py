"""Redis connection pool + ARQ job enqueue.

Reads REDIS_URL from env or settings.redis_url.
"""

import logging
from typing import Optional

import redis.asyncio as redis
from arq import create_pool, ArqRedis

from aios.config import settings

logger = logging.getLogger(__name__)

_redis_pool: Optional[ArqRedis] = None


async def get_redis_pool() -> ArqRedis:
    """Return shared ARQ Redis pool — created on first call."""
    global _redis_pool
    if _redis_pool is None:
        url = settings.redis_url or "redis://localhost:6379"
        _redis_pool = await create_pool(url)
        logger.info("Redis pool connected to %s", url.split("@")[-1] if "@" in url else url)
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
