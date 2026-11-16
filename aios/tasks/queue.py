"""Redis connection pool + ARQ job enqueue.

Reads REDIS_URL from env or settings.redis_url.
"""

import logging
import os
import time
from typing import Optional
from urllib.parse import urlparse

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from aios.config import settings

logger = logging.getLogger(__name__)

_redis_pool: Optional[ArqRedis] = None
# arq retries a dead redis for ~5s per call. Without this, every webhook or API
# turn paid that during an outage; now the first caller pays and the rest fail
# fast until the cooldown expires.
_pool_retry_after = 0.0
_POOL_RETRY_COOLDOWN_S = 5.0


def _parse_redis(url: str) -> RedisSettings:
    """Parse redis:// URL into RedisSettings — SASL (user:pass) + TLS (rediss://).

    REDIS_HOST/REDIS_PORT are the fallback when the URL is unset or has no host.
    Compose sets them (`REDIS_HOST: redis`), so ignoring them pointed both
    processes at localhost instead of the Redis service.
    """
    parsed = urlparse(url) if url else None
    # No URL at all → REDIS_HOST/PORT are the only signal. Compose sets them,
    # so the old hardcoded "redis://localhost:6379" default dialled localhost.
    if parsed is None:
        parsed = urlparse(f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', '6379')}/0")
    # fallback para envs quando URL sem credenciais (SASL)
    username = parsed.username or settings.redis_username or None
    password = parsed.password or settings.redis_password or None
    # rediss:// → TLS
    is_tls = parsed.scheme == "rediss"
    # host is a plain str here. RedisSettings widens it to str | cluster-list, so
    # consumers have to narrow it back; this function is the single source.
    return RedisSettings(
        host=parsed.hostname or os.getenv("REDIS_HOST") or "localhost",
        port=parsed.port or int(os.getenv("REDIS_PORT", "6379")),
        database=int(parsed.path.lstrip("/") or "0"),
        username=username,
        password=password,
        ssl=is_tls,
    )


# Lease holders (channel pollers) share one key and store their owner id as the
# value. A per-replica key made `SET NX` succeed on every replica, so the "lock"
# never excluded anyone. Renew/release must only touch our own lease, hence Lua.
_LEASE_RENEW_LUA = (
    "if redis.call('get',KEYS[1])==ARGV[1] then "
    "return redis.call('expire',KEYS[1],ARGV[2]) else return 0 end"
)
_LEASE_RELEASE_LUA = (
    "if redis.call('get',KEYS[1])==ARGV[1] then "
    "return redis.call('del',KEYS[1]) else return 0 end"
)


async def acquire_lease(pool, key: str, owner: str, ttl: int) -> bool:
    return bool(await pool.set(key, owner, nx=True, ex=ttl))


async def renew_lease(pool, key: str, owner: str, ttl: int) -> bool:
    return bool(await pool.eval(_LEASE_RENEW_LUA, 1, key, owner, ttl))


async def release_lease(pool, key: str, owner: str) -> bool:
    return bool(await pool.eval(_LEASE_RELEASE_LUA, 1, key, owner))


async def get_redis_pool() -> ArqRedis:
    """Return shared ARQ Redis pool — created on first call."""
    global _redis_pool, _pool_retry_after
    if _redis_pool is None:
        if time.monotonic() < _pool_retry_after:
            raise ConnectionError("redis pool unavailable (retry cooldown)")
        # "" when unset, so _parse_redis falls back to REDIS_HOST/PORT instead of
        # a hardcoded localhost that compose never publishes.
        url = settings.redis_url or os.getenv("REDIS_URL", "")
        redis_settings = _parse_redis(url)
        try:
            _redis_pool = await create_pool(redis_settings)
        except Exception:
            _pool_retry_after = time.monotonic() + _POOL_RETRY_COOLDOWN_S
            raise
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


async def enqueue_task(task_name: str, payload: dict, **job_kwargs):
    """Lightweight task enqueue — returns the ARQ job, or None if Redis is unavailable."""
    try:
        pool = await get_redis_pool()
        return await pool.enqueue_job(task_name, payload, **job_kwargs)
    except Exception:
        # Dropped task. debug hid this completely; a down Redis means lost
        # work and the only signal was silence. Warning, not error: the
        # fallback to no-op is deliberate when Redis is unavailable.
        logger.warning("enqueue_task fallback (no redis): %s", task_name)
        return None


async def close_pool():
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.close()
        _redis_pool = None
