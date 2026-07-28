"""Rate limiting configuration using slowapi.

Usage:
    from aios.api.ratelimit import limiter

    @router.get("/endpoint")
    @limiter.limit("5/minute")
    async def my_endpoint(request: Request):
        ...
"""

import jwt
from slowapi import Limiter
from slowapi.util import get_remote_address

from aios.config import settings


def _get_org_key(request) -> str:
    """Extract org_id from JWT for per-tenant rate limiting. Falls back to IP."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = jwt.decode(auth[7:], settings.jwt_secret, algorithms=[settings.jwt_algorithm])
            org_id = payload.get("org")
            if org_id:
                return f"org:{org_id}"
        except jwt.PyJWTError:
            pass
    return get_remote_address(request)


# ponytail: in-memory storage. Redis-backed for multi-worker deployments.
_rpm = 10000 if settings.debug else settings.rate_limit_per_minute
limiter = Limiter(key_func=_get_org_key, default_limits=[f"{_rpm}/minute"])
