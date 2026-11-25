"""Auth deps: JWT validation, dashboard cookie auth."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException
from fastapi import Request as FastAPIRequest

from aios.api.auth import _is_login_allowed, _verify_jwt_token, _create_jwt_token
from aios.db.backend import DatabaseBackend, get_db_backend
from aios.db.models import Organization, User

logger = logging.getLogger(__name__)


async def _record_auth_failure_best_effort(db, *, org_id: str | None, actor_id: str | None = None, payload: dict | None = None) -> None:
    if not org_id or db is None:
        return
    try:
        from aios.governance.security import record_auth_failure

        await record_auth_failure(
            db,
            org_id=str(org_id),
            actor_id=str(actor_id) if actor_id else None,
            payload=payload or {},
        )
    except Exception:
        pass


async def get_current_user(
    # FastAPI injects Request by annotation and rejects `Request | None` as a
    # Pydantic field, so the default stays None and only the type is relaxed.
    request: FastAPIRequest = None,  # type: ignore[assignment]
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
            await _record_auth_failure_best_effort(
                db,
                org_id=getattr(user, "org_id", None),
                actor_id=getattr(user, "id", None),
                payload={"reason": "allowlist_denied", "source": "api.deps.get_current_user"},
            )
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


async def get_superadmin(
    user: User = Depends(get_current_user),
    db: DatabaseBackend = Depends(get_db_backend),
) -> User:
    """Restrict to workspace administrators.

    /api/dev/* runs prompts and builds with repo-wide file and shell access.
    Any authenticated member is too broad; org owners and platform
    superadmins only.
    """
    if user.role not in ("superadmin", "owner"):
        org_id = getattr(user, "org_id", None)
        if db is not None and org_id:
            source = "api.deps.superadmin"
            try:
                from aios.governance.security import record_security_event

                event = await record_security_event(
                    db,
                    org_id=str(org_id),
                    source=source,
                    event_type="security.authz.denied",
                    severity="medium",
                    actor_type="human",
                    actor_id=str(getattr(user, "id", "") or "") or None,
                    payload={"reason": "superadmin_required", "path_source": source},
                )
                if event is not None:
                    await db.commit()
            except Exception:
                logger.debug("authz denied metric skipped", exc_info=True)
        raise HTTPException(403, "requer administrador")
    return user


def verify_org_access(org_id: str, resource) -> None:
    org_attr = "id" if isinstance(resource, Organization) else "org_id"
    if not resource or getattr(resource, org_attr, None) != org_id:
        raise HTTPException(404)


async def verify_org_access_async(
    org_id: str,
    resource,
    *,
    db: DatabaseBackend | None = None,
    actor_id: str | None = None,
    actor_type: str | None = "human",
    source: str = "api.deps.verify_org_access",
    payload: dict | None = None,
) -> None:
    """Like verify_org_access, but emits best-effort cross-tenant mismatch metric.

    Sync verify_org_access stays for backward compat; it has no db/actor context.
    Use this async variant where db is available so cross-tenant 404 mismatches
    produce deterministic security telemetry without leaking resource existence.
    """
    org_attr = "id" if isinstance(resource, Organization) else "org_id"
    resource_org = getattr(resource, org_attr, None) if resource else None
    if not resource or resource_org != org_id:
        if (
            db is not None
            and resource is not None
            and resource_org is not None
            and str(resource_org) != str(org_id)
        ):
            try:
                from aios.governance.security import record_cross_tenant_block_if_mismatch

                await record_cross_tenant_block_if_mismatch(
                    db,
                    org_id=str(org_id),
                    resource=resource,
                    resource_org_attr=org_attr,
                    source=source,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    payload=payload,
                )
            except Exception:
                pass
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
            await _record_auth_failure_best_effort(
                db,
                org_id=getattr(user, "org_id", None),
                actor_id=getattr(user, "id", None),
                payload={"reason": "allowlist_denied", "source": "api.deps.get_dashboard_user"},
            )
            return None
        return user
    return None
