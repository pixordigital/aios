"""ARQ worker entry point — processes background jobs.

Starts an ARQ worker that picks up queued jobs from Redis.
Registered jobs in aios.tasks.jobs.FUNCTIONS.
Reads Redis URL from settings.redis_url or REDIS_URL env.

Usage:
    python -m aios.tasks.worker
    aios-worker
"""

import os
from arq import cron
from arq.connections import RedisSettings
from aios.config import settings
from .jobs import FUNCTIONS


def _parse_redis(redis_url: str) -> RedisSettings:
    """Parse redis:// URL into RedisSettings."""
    from urllib.parse import urlparse
    parsed = urlparse(redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or "0"),
        password=parsed.password or None,
    )


class WorkerSettings:
    """ARQ worker configuration — used by `arq aios.tasks.worker.WorkerSettings`."""
    functions = FUNCTIONS
    redis_settings = _parse_redis(settings.redis_url or os.getenv("REDIS_URL", "redis://localhost:6379"))
    max_jobs = 20
    job_timeout = 300
    poll_delay = 0.2
    health_check_interval = 60
    log_results = True
    keep_result = 3600
    retry_jobs = True

    @staticmethod
    async def on_startup(ctx):
        from aios.db.engine import init_db
        try:
            await init_db()
        except Exception:
            pass

    @staticmethod
    async def on_shutdown(ctx):
        from aios.tasks.queue import close_pool
        try:
            await close_pool()
        except Exception:
            pass


# ponytail: async def run() kept for backward compat with aios-worker script
async def run():
    """Entry point for ``aios-worker`` script — blocks on event loop."""
    from arq.worker import Worker
    worker = Worker(functions=FUNCTIONS, redis_settings=WorkerSettings.redis_settings)
    await worker.run()


def main():
    """CLI entry point — uses arq's built-in worker loop."""
    from arq.cli import run_worker
    run_worker(WorkerSettings)


if __name__ == "__main__":
    main()
