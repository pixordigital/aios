"""ARQ worker entry point — processes background jobs.

Starts an ARQ worker that picks up queued jobs from Redis.
Registered jobs in aios.tasks.jobs.FUNCTIONS.
Reads Redis URL from settings.redis_url or REDIS_URL env.
"""

import os
from arq import Worker
from aios.config import settings
from .jobs import FUNCTIONS


async def run():
    """Entry point for ``aios-worker`` script."""
    redis_url = settings.redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
    worker = Worker(FUNCTIONS, redis_settings={"address": redis_url})
    await worker.run()
