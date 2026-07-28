"""Rate limiting configuration using slowapi.

Usage:
    from aios.api.ratelimit import limiter

    @router.get("/endpoint")
    @limiter.limit("5/minute")
    async def my_endpoint(request: Request):
        ...
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from aios.config import settings

# ponytail: in-memory storage. Redis-backed for multi-worker deployments.
_rpm = 10000 if settings.debug else settings.rate_limit_per_minute
limiter = Limiter(key_func=get_remote_address, default_limits=[f"{_rpm}/minute"])
