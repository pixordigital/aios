"""Optional Postgres RLS org-context wiring.

Fail-safe by default:
- no-op when AIOS_RLS_CONTEXT_ENABLED is false (default)
- no-op on SQLite / non-Postgres dialects
- no-op when org_id is missing/empty

RLS enforcement itself is gated by alembic scaffold migration
(h5i6j7k8l9m0_rls_scaffold_optional.py) and AIOS_APPLY_RLS_SCAFFOLD=1.
This module only sets `app.current_org_id` for the current transaction so
policies can evaluate when RLS is enabled.

Background jobs/workers: pass org_id for RLS-enabled mode. Prefer
`db_session(org_id=...)` or `bind_session_rls(session, org_id)` for raw
AsyncSession paths so policies can evaluate when enabled.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from aios.config import settings

# Request/task scoped org id used by optional RLS context wiring.
current_rls_org_id: ContextVar[str | None] = ContextVar("aios_rls_org_id", default=None)


def rls_context_enabled() -> bool:
    return bool(getattr(settings, "rls_context_enabled", False))


def _is_postgres_session(session: AsyncSession) -> bool:
    try:
        bind = session.get_bind()
    except Exception:
        return False
    dialect = getattr(getattr(bind, "dialect", None), "name", "")
    return dialect == "postgresql"


def normalize_org_id(org_id: str | None) -> str | None:
    if org_id is None:
        return None
    value = str(org_id).strip()
    return value or None


def set_rls_org_id(org_id: str | None) -> Token[str | None]:
    """Set task-scoped RLS org id; caller must reset token."""
    return current_rls_org_id.set(normalize_org_id(org_id))


def reset_rls_org_id(token: Token[str | None]) -> None:
    current_rls_org_id.reset(token)


def get_rls_org_id() -> str | None:
    return normalize_org_id(current_rls_org_id.get())


async def apply_rls_org_context(session: AsyncSession, org_id: str | None = None) -> bool:
    """Apply `app.current_org_id` for current transaction when safe/enabled.

    Returns True when SET LOCAL/set_config was executed, False on no-op.
    Safe no-op on sqlite/disabled/missing org. Uses set_config(..., true)
    so value is transaction-local.
    """
    if not rls_context_enabled():
        return False
    if not _is_postgres_session(session):
        return False
    resolved = normalize_org_id(org_id) if org_id is not None else get_rls_org_id()
    if not resolved:
        return False
    # set_config(name, value, is_local=true) == SET LOCAL; parameterized.
    await session.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"),
        {"org_id": resolved},
    )
    return True


async def bind_session_rls(session: AsyncSession, org_id: str | None) -> Token[str | None] | None:
    """Bind org_id to session/context for RLS-enabled mode.

    Background jobs/workers: pass org_id for RLS-enabled mode. Sets task context
    and applies transaction-local Postgres RLS context when enabled. Returns token
    for reset, or None when no org binding was needed.
    """
    resolved = normalize_org_id(org_id)
    if not resolved:
        return None
    token = set_rls_org_id(resolved)
    try:
        await apply_rls_org_context(session, org_id=resolved)
    except Exception:
        reset_rls_org_id(token)
        raise
    return token


def rls_session_kwargs(org_id: str | None = None) -> dict[str, Any]:
    """Helper for explicit call sites; no DB side effects."""
    return {"org_id": normalize_org_id(org_id), "enabled": rls_context_enabled()}
