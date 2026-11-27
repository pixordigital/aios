"""Controlled runtime wiring for fail-closed business execution.

No autonomous money movement. Adapters execute only when explicitly approved and
configured in settings/env. Side effects require idempotency keys.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from aios.core.adapters.registry import build_business_execution_registry
from aios.core.business_execution import (
    ExecutionDenied,
    ExecutionRegistry,
    ExecutionResult,
    IdempotencyStore,
    InMemoryIdempotencyStore,
)

logger = logging.getLogger(__name__)

_IDEMPOTENCY_STORE: IdempotencyStore | None = None
_IDEMPOTENCY_STORE_LOCK = threading.Lock()
_IDEMPOTENCY_STORE_KIND: str = "unknown"  # db|memory|unknown


def _resolve_settings(settings: Any) -> Any:
    if settings is not None:
        return settings
    try:
        from aios.config import settings as app_settings

        return app_settings
    except Exception:
        return None


def _idempotency_required(settings: Any) -> bool:
    """Resolve fail-closed idempotency requirement.

    Safe default: require durable store. Explicit flag wins:
    `AIOS_BUSINESS_IDEMPOTENCY_REQUIRED=false` allows in-memory fallback for
    local dev/test only. If flag is unset on settings object, infer prod-like
    env as required; debug/dev defaults to not required for convenience.
    """

    if settings is None:
        settings = _resolve_settings(None)
    if settings is None:
        return True
    # Explicit attr wins (Settings has safe default True).
    if hasattr(settings, "business_idempotency_required"):
        val = getattr(settings, "business_idempotency_required")
        if val is not None:
            return bool(val)
    env = str(getattr(settings, "env", "") or getattr(settings, "environment", "") or "").lower()
    if env in {"prod", "production", "staging"}:
        return True
    if bool(getattr(settings, "debug", False)):
        return False
    # Ambiguous/legacy test settings without attr: preserve convenience.
    if not hasattr(settings, "business_idempotency_required"):
        return False
    return True


def get_business_idempotency_store(*, settings: Any = None) -> IdempotencyStore:
    """Return idempotency store for business execution side effects.

    Prefers DB-backed durable store. When durable store unavailable:
    - if `business_idempotency_required` resolves True, raise ExecutionDenied
      (fail closed; no silent in-memory fallback).
    - else return process-local in-memory store (dev/test convenience only).
    """

    global _IDEMPOTENCY_STORE, _IDEMPOTENCY_STORE_KIND
    if _IDEMPOTENCY_STORE is not None:
        return _IDEMPOTENCY_STORE
    with _IDEMPOTENCY_STORE_LOCK:
        if _IDEMPOTENCY_STORE is not None:
            return _IDEMPOTENCY_STORE
        resolved = _resolve_settings(settings)
        required = _idempotency_required(resolved)
        try:
            from aios.core.business_idempotency import DBIdempotencyStore

            db_store = DBIdempotencyStore.from_settings(resolved)
        except Exception as exc:
            logger.warning("DB business idempotency store unavailable: %s", exc)
            db_store = None
        if db_store is not None:
            _IDEMPOTENCY_STORE = db_store
            _IDEMPOTENCY_STORE_KIND = "db"
            logger.info("business_execution idempotency: db-backed durable store")
        else:
            if required:
                _IDEMPOTENCY_STORE_KIND = "unavailable"
                raise ExecutionDenied(
                    "durable idempotency store required for business side effects; "
                    "set AIOS_BUSINESS_IDEMPOTENCY_REQUIRED=false only for local dev/test"
                )
            _IDEMPOTENCY_STORE = InMemoryIdempotencyStore()
            _IDEMPOTENCY_STORE_KIND = "memory"
            logger.warning(
                "business_execution idempotency: falling back to process-local in-memory store; "
                "claims are not durable across restart/workers (AIOS_BUSINESS_IDEMPOTENCY_REQUIRED=false)"
            )
    return _IDEMPOTENCY_STORE


def is_business_idempotency_durable(store: Any = None) -> bool:
    if store is None:
        s = get_business_idempotency_store()
        if hasattr(s, "durable"):
            try:
                return bool(s.durable)
            except Exception:
                return False
        return _IDEMPOTENCY_STORE_KIND == "db"
    if hasattr(store, "durable"):
        try:
            return bool(store.durable)
        except Exception:
            return False
    return False


def reclaim_stale_business_idempotency_processing(
    *,
    settings: Any = None,
    idempotency_store: Any = None,
    scope: str | None = None,
    org_id: str | None = None,
    older_than_seconds: int | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Ops/test helper: mark stale processing claims failed/reclaimable.

    Fail-closed: does not re-execute side effects. Returns reclaimed item count/details.
    """
    store = idempotency_store or get_business_idempotency_store(settings=settings)
    fn = getattr(store, "reclaim_stale_processing", None)
    if not callable(fn):
        raise RuntimeError("idempotency store does not support stale processing reclaim")
    return fn(
        scope=scope,
        org_id=org_id,
        older_than_seconds=older_than_seconds,
        limit=limit,
    )


def build_controlled_business_registry(
    *,
    settings: Any = None,
    db: Any = None,
    audit_callback: Any = None,
    idempotency_store: Any = None,
) -> ExecutionRegistry:
    """Build fail-closed registry for controlled runtime paths.

    Approval comes only from settings/config. Callers cannot pass approval flags.
    """

    store = (
        get_business_idempotency_store(settings=settings)
        if idempotency_store is None
        else idempotency_store
    )
    resolved = _resolve_settings(settings)
    require_durable = _idempotency_required(resolved)
    return build_business_execution_registry(
        settings=resolved,
        db=db,
        audit_callback=audit_callback,
        sandbox_senders=None,
        approved_adapters=None,
        idempotency_store=store,
        require_durable_idempotency=require_durable,
        require_org_scope=True,
    )


def execute_controlled_business_action(
    *,
    adapter: str,
    action: str,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    side_effect: bool = True,
    settings: Any = None,
    db: Any = None,
    audit_callback: Any = None,
    idempotency_store: Any = None,
) -> ExecutionResult:
    """Controlled entrypoint. Fail-closed by default.

    Requires explicit adapter approval/config via settings. Requires idempotency
    key for side effects. Does not enable autonomous money movement.
    """

    registry = build_controlled_business_registry(
        settings=settings,
        db=db,
        audit_callback=audit_callback,
        idempotency_store=idempotency_store,
    )
    return registry.execute(
        adapter=adapter,
        action=action,
        payload=payload,
        idempotency_key=idempotency_key,
        side_effect=side_effect,
    )


__all__ = [
    "ExecutionDenied",
    "ExecutionRegistry",
    "ExecutionResult",
    "build_controlled_business_registry",
    "execute_controlled_business_action",
    "get_business_idempotency_store",
    "is_business_idempotency_durable",
    "reclaim_stale_business_idempotency_processing",
]
