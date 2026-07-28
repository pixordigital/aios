"""Auth deps: JWT validation, API key, dashboard cookie auth."""
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException, Request as FastAPIRequest
from sqlalchemy import select

from aios.config import settings
from aios.db.backend import get_db_backend, DatabaseBackend
from aios.db.engine import async_session
from aios.db.models import User


def _constant_time_compare(a: str, b: str) -> bool:
    return secrets.compare_digest(a, b)


async def get_current_user(
    db: DatabaseBackend = Depends(get_db_backend),
    authorization: str = Header(None),
    x_api_key: str = Header(None),
) -> User:
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        try:
            payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        except jwt.PyJWTError:
            raise HTTPException(401, "Invalid token")

        # enforce token is an access token, not a refresh token
        if payload.get("type") != "access":
            raise HTTPException(401, "Invalid token type")

        user = await db.get(User, payload["sub"])
        if not user:
            raise HTTPException(401, "Invalid token")
        return user

    if x_api_key:
        result = await db.execute(
            select(User).where(User.api_key_hash.isnot(None))
        )
        for user in result.scalars():
            if user.api_key_hash and _constant_time_compare(user.api_key_hash, x_api_key):
                return user

    raise HTTPException(401, "Not authenticated")


async def get_org_id(user: User = Depends(get_current_user)) -> str:
    return user.org_id


def verify_org_access(org_id: str, resource) -> None:
    """Verify resource belongs to org. Raise 404 if not."""
    if not resource or getattr(resource, "org_id", None) != org_id:
        raise HTTPException(404)


# ─── Dashboard cookie auth ───

COOKIE_NAME = "aios_token"
COOKIE_MAX_AGE = 86400 * 7


def create_jwt_token(user_id: str, org_id: str) -> str:
    payload = {
        "sub": user_id, "org": org_id,
        "type": "access",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(seconds=COOKIE_MAX_AGE),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def get_dashboard_user(request: FastAPIRequest) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    async with async_session() as db:
        return await db.get(User, payload["sub"])
