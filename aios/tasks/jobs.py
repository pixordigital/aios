"""Async job definitions for ARQ worker.

Each top-level function is a job ARQ can execute.
Registered in FUNCTIONS list for the worker to discover.
"""

import logging

from aios.core.delivery import deliver_message

logger = logging.getLogger(__name__)


async def example_job(ctx, *args, **kwargs):
    logger.info("Example job ran with ctx=%s", ctx)
    return "ok"


# ARQ worker function registry
FUNCTIONS = [
    example_job,
    deliver_message,
]
