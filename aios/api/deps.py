"""Auth deps: JWT validation, dashboard cookie auth."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException
from fastapi import Request as FastAPIRequest

from aios.api.auth import _is_login_allowed, _verify_jwt_token, _create_jwt_token
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import User

logger = logging.getLogger(__name__)


async def get_current_user(
    request: FastAPIRequest = None,
    db: DatabaseBackend = Depends(get_db_backend),
    authorization: str = Header(None),
) -> User:
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        payload = _verify_jwt_token(token)
        if not payload:
            raise HTTPException(401, "Token inválido")

        # enforce token is an access token, not a refresh token
        if payload.get("type") != "access":
            raise HTTPException(401, "Tipo de token inválido")

        user = await db.get(User, payload["sub"])
        if not user:
            raise HTTPException(401, "Token inválido")
        # Re-checked on EVERY authenticated request, not just at login: this
        # is what invalidates existing sessions the moment an address leaves
        # the allowlist (or was never on it), instead of at token expiry.
        if not _is_login_allowed(user.email):
            logger.warning("rejected authenticated request for non-allowlisted account")
            raise HTTPException(401, "Token inválido")
        return user

    # x-api-key header support was removed: api_key_hash was never populated
    # and nothing ever sent the header, so the branch could never
    # authenticate anyone. Bearer JWT and dashboard cookie remain.

    # Fall back to dashboard cookie so the browser's fetch() calls to /api/*
    # work without embedding the JWT in client-side JS.
    if request is not None:
        user = await get_dashboard_user(request)
        if user:
            return user

    raise HTTPException(401, "Not authenticated")


async def get_org_id(user: User = Depends(get_current_user)) -> str:
    return user.org_id


async def get_superadmin(user: User = Depends(get_current_user)) -> User:
    """Restrict to workspace administrators.

    /api/dev/* runs prompts and builds with repo-wide file and shell access.
    Any authenticated member is too broad; org owners and platform
    superadmins only.
    """
    if user.role not in ("superadmin", "owner"):
        raise HTTPException(403, "requer administrador")
    return user


def verify_org_access(org_id: str, resource) -> None:
    if not resource or getattr(resource, "org_id", None) != org_id:
        raise HTTPException(404)


def require_org_id(request: FastAPIRequest):
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        raise HTTPException(403, detail="org_id missing — RLS enforced")
    return org_id


async def audit_log(
    org_id: str,
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict | None = None,
):
    try:
        from aios.db.engine import async_session
        from aios.db.models import AuditLog

        async with async_session() as sess:
            sess.add(
                AuditLog(
                    org_id=org_id,
                    user_id=user_id,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    details=details or {},
                )
            )
            await sess.commit()
    except Exception:
        pass


# ─── Dashboard cookie auth ───

COOKIE_NAME = "aios_token"
COOKIE_MAX_AGE = 86400 * 7


def create_jwt_token(user_id: str, org_id: str) -> str:
    token, _ = _create_jwt_token(
        {
            "sub": user_id,
            "org": org_id,
            "type": "access",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(seconds=COOKIE_MAX_AGE),
        },
        token_type="access"
    )
    return token


async def get_dashboard_user(request: FastAPIRequest) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    payload = _verify_jwt_token(token)
    if not payload:
        return None
    # Sessions are access tokens, not refresh tokens. Without this a stolen
    # 30-day refresh token worked as a dashboard cookie, bypassing the much
    # shorter access-token lifetime. Same enforcement get_current_user applies.
    if payload.get("type") != "access":
        return None
    # Route through FastAPI DI so tests' dependency_overrides apply
    resolver = request.app.dependency_overrides.get(get_db_backend, get_db_backend)
    async for db in resolver():
        user = await db.get(User, payload["sub"])
        if user and not _is_login_allowed(user.email):
            logger.warning("rejected dashboard session for non-allowlisted account")
            return None
        return user
    return None
