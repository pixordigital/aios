"""Fail-closed execution scaffold for running a business.

Additive scaffold only: no real integrations, no credentials. Side-effect
execution requires an explicitly configured and approved adapter plus an
idempotency key. All decisions emit an audit callback.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

AuditCallback = Callable[[dict[str, Any]], None]


@runtime_checkable
class IdempotencyStore(Protocol):
    """Claim/lookup hook for side-effect idempotency.

    Implementations must make claim atomic for their durability scope.
    Default in-memory store is process-local only; durable implementations
    should back claims with DB unique constraint or equivalent.
    Durable stores may also expose get/complete/fail for replay and state.
    """

    def claim(self, key: str) -> bool:
        """Return True when key newly claimed, False when duplicate."""
        ...


class ExecutionDenied(PermissionError):
    """Execution denied by fail-closed policy."""


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    adapter: str
    action: str
    idempotency_key: str
    status: str
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ExecutionAdapter(Protocol):
    """Adapter contract for business side effects.

    Real integrations must be explicitly configured and approved out of band.
    This scaffold does not ship credentials or live adapters.
    """

    name: str
    approved: bool

    def execute(
        self,
        *,
        action: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> ExecutionResult: ...


class InMemoryIdempotencyStore:
    """Process-local idempotency claims.

    Limitation: not durable across process restart and not shared across workers.
    Use a DB-backed store for durable production guarantees.
    """

    durable = False

    def __init__(self) -> None:
        self._keys: set[str] = set()
        self._lock = threading.Lock()

    def claim(self, key: str) -> bool:
        k = str(key or "").strip()
        if not k:
            return False
        with self._lock:
            if k in self._keys:
                return False
            self._keys.add(k)
            return True


class ExecutionRegistry:
    """Registry of execution adapters with fail-closed enforcement."""

    def __init__(
        self,
        *,
        audit_callback: AuditCallback | None = None,
        idempotency_store: IdempotencyStore | None = None,
        require_durable_idempotency: bool = False,
        require_org_scope: bool = True,
    ) -> None:
        self._adapters: dict[str, ExecutionAdapter] = {}
        self._audit_callback = audit_callback
        self._idempotency_store = idempotency_store
        self._require_durable_idempotency = bool(require_durable_idempotency)
        self._require_org_scope = bool(require_org_scope)
        self.missing_config: dict[str, list[str]] = {}

    def register(self, adapter: ExecutionAdapter) -> None:
        name = str(getattr(adapter, "name", "") or "").strip()
        if not name:
            raise ValueError("adapter.name required")
        self._adapters[name] = adapter

    def get(self, name: str) -> ExecutionAdapter | None:
        return self._adapters.get(name)

    def _audit(self, event: dict[str, Any]) -> None:
        payload = dict(event)
        logger.info("business_execution.audit %s", payload)
        if self._audit_callback is not None:
            self._audit_callback(payload)

    def _deny(
        self,
        *,
        adapter: str,
        action: str,
        idempotency_key: str,
        reason: str,
    ) -> ExecutionDenied:
        self._audit(
            {
                "event": "business_execution.denied",
                "adapter": adapter,
                "action": action,
                "idempotency_key": idempotency_key,
                "ok": False,
                "reason": reason,
            }
        )
        return ExecutionDenied(reason)

    def execute(
        self,
        *,
        adapter: str,
        action: str,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        side_effect: bool = True,
    ) -> ExecutionResult:
        adapter_name = str(adapter or "").strip()
        action_name = str(action or "").strip()
        key = str(idempotency_key or "").strip()
        data = dict(payload or {})

        if not adapter_name:
            raise self._deny(
                adapter=adapter_name,
                action=action_name,
                idempotency_key=key,
                reason="adapter not configured",
            )

        if side_effect and not key:
            raise self._deny(
                adapter=adapter_name,
                action=action_name,
                idempotency_key=key,
                reason="idempotency_key required for side effects",
            )

        org_id = str(data.get("org_id") or "").strip() or None
        if side_effect and self._require_org_scope and not org_id:
            raise self._deny(
                adapter=adapter_name,
                action=action_name,
                idempotency_key=key,
                reason="org_id required for side-effect idempotency scope",
            )

        impl = self._adapters.get(adapter_name)
        if impl is None:
            raise self._deny(
                adapter=adapter_name,
                action=action_name,
                idempotency_key=key,
                reason=f"adapter not configured: {adapter_name}",
            )

        if not bool(getattr(impl, "approved", False)):
            raise self._deny(
                adapter=adapter_name,
                action=action_name,
                idempotency_key=key,
                reason=f"adapter not approved: {adapter_name}",
            )

        if side_effect:
            if self._idempotency_store is None:
                if self._require_durable_idempotency:
                    raise self._deny(
                        adapter=adapter_name,
                        action=action_name,
                        idempotency_key=key,
                        reason="durable idempotency store required for side effects",
                    )
            else:
                durable = bool(getattr(self._idempotency_store, "durable", True))
                if self._require_durable_idempotency and not durable:
                    raise self._deny(
                        adapter=adapter_name,
                        action=action_name,
                        idempotency_key=key,
                        reason="durable idempotency store required for side effects",
                    )
                claimed = False
                try:
                    claim_fn = self._idempotency_store.claim
                    try:
                        claimed = bool(
                            claim_fn(key, org_id=org_id, adapter=adapter_name, action=action_name)
                        )
                    except TypeError:
                        claimed = bool(claim_fn(key))
                except Exception as exc:
                    raise self._deny(
                        adapter=adapter_name,
                        action=action_name,
                        idempotency_key=key,
                        reason=f"idempotency store error: {exc}",
                    )
                if not claimed:
                    replay = self._replay_idempotency(
                        key=key, org_id=org_id, adapter=adapter_name, action=action_name
                    )
                    self._audit(
                        {
                            "event": "business_execution.duplicate",
                            "adapter": adapter_name,
                            "action": action_name,
                            "idempotency_key": key,
                            "ok": replay.ok,
                            "status": replay.status,
                            "durable": replay.data.get("durable", False),
                        }
                    )
                    return replay

        self._audit(
            {
                "event": "business_execution.start",
                "adapter": adapter_name,
                "action": action_name,
                "idempotency_key": key,
                "side_effect": side_effect,
                "ok": None,
            }
        )

        try:
            result = impl.execute(
                action=action_name,
                payload=data,
                idempotency_key=key,
            )
        except Exception as exc:
            self._idempotency_fail(
                key=key,
                org_id=org_id,
                error=str(exc),
            )
            self._audit(
                {
                    "event": "business_execution.error",
                    "adapter": adapter_name,
                    "action": action_name,
                    "idempotency_key": key,
                    "ok": False,
                    "reason": str(exc),
                }
            )
            raise

        if not isinstance(result, ExecutionResult):
            raise self._deny(
                adapter=adapter_name,
                action=action_name,
                idempotency_key=key,
                reason="adapter returned invalid result",
            )

        self._idempotency_complete(
            key=key,
            org_id=org_id,
            result=result,
        )
        self._audit(
            {
                "event": "business_execution.result",
                "adapter": adapter_name,
                "action": action_name,
                "idempotency_key": key,
                "ok": result.ok,
                "status": result.status,
            }
        )
        return result

    def _replay_idempotency(
        self,
        *,
        key: str,
        org_id: str | None,
        adapter: str,
        action: str,
    ) -> ExecutionResult:
        store = self._idempotency_store
        if store is not None and hasattr(store, "get"):
            try:
                rec = store.get(key, org_id=org_id)
            except TypeError:
                rec = store.get(key)
            except Exception as exc:
                # Fail closed on durable lookup errors; never re-execute side effect.
                raise self._deny(
                    adapter=adapter,
                    action=action,
                    idempotency_key=key,
                    reason=f"idempotency lookup error: {exc}",
                )
            if rec is not None:
                status = str(getattr(rec, "status", "") or "duplicate")
                stored = getattr(rec, "result", None)
                if isinstance(stored, dict) and stored.get("adapter") and stored.get("action"):
                    return ExecutionResult(
                        ok=bool(stored.get("ok", True)),
                        adapter=str(stored.get("adapter") or adapter),
                        action=str(stored.get("action") or action),
                        idempotency_key=key,
                        status=str(stored.get("status") or ("duplicate" if status == "completed" else status)),
                        detail=str(stored.get("detail") or "idempotency replay"),
                        data={**dict(stored.get("data") or {}), "duplicate": True, "durable": True, "idempotency_status": status},
                    )
                if status == "processing":
                    stale_processing = bool(getattr(rec, "stale_processing", False))
                    age = getattr(rec, "processing_age_seconds", None)
                    if stale_processing:
                        # Fail closed: stale in-flight claim means prior execution outcome unknown.
                        # Never auto-retry/re-execute; ops/test must inspect and reclaim explicitly.
                        return ExecutionResult(
                            ok=False,
                            adapter=adapter,
                            action=action,
                            idempotency_key=key,
                            status="stale_processing",
                            detail=(
                                "idempotency_key processing claim is stale; side effect not re-executed. "
                                "Inspect/reclaim via DBIdempotencyStore.reclaim_stale_processing() "
                                "before retrying with a new idempotency key."
                            ),
                            data={
                                "duplicate": True,
                                "durable": True,
                                "idempotency_status": status,
                                "stale_processing": True,
                                "processing_age_seconds": age,
                            },
                        )
                    # Do not re-execute side effect while original claim in-flight.
                    return ExecutionResult(
                        ok=True,
                        adapter=adapter,
                        action=action,
                        idempotency_key=key,
                        status="duplicate_processing",
                        detail="idempotency_key is already processing; side effect not re-executed",
                        data={"duplicate": True, "durable": True, "idempotency_status": status},
                    )
                if status == "failed":
                    return ExecutionResult(
                        ok=False,
                        adapter=adapter,
                        action=action,
                        idempotency_key=key,
                        status="duplicate_failed",
                        detail=str(getattr(rec, "error", "") or "previous idempotent attempt failed"),
                        data={"duplicate": True, "durable": True, "idempotency_status": status},
                    )
                return ExecutionResult(
                    ok=True,
                    adapter=adapter,
                    action=action,
                    idempotency_key=key,
                    status="duplicate",
                    detail="idempotency_key already executed",
                    data={"duplicate": True, "durable": True, "idempotency_status": status},
                )
        return ExecutionResult(
            ok=True,
            adapter=adapter,
            action=action,
            idempotency_key=key,
            status="duplicate",
            detail="idempotency_key already executed",
            data={"duplicate": True},
        )

    def _idempotency_complete(self, *, key: str, org_id: str | None, result: ExecutionResult) -> None:
        store = self._idempotency_store
        if not key or store is None or not hasattr(store, "complete"):
            return
        payload = {
            "ok": result.ok,
            "adapter": result.adapter,
            "action": result.action,
            "idempotency_key": result.idempotency_key,
            "status": result.status,
            "detail": result.detail,
            "data": result.data,
        }
        try:
            try:
                store.complete(key, result=payload, org_id=org_id)
            except TypeError:
                store.complete(key, result=payload)
        except Exception as exc:
            logger.warning("business_execution idempotency complete failed: %s", exc)

    def _idempotency_fail(self, *, key: str, org_id: str | None, error: str) -> None:
        store = self._idempotency_store
        if not key or store is None or not hasattr(store, "fail"):
            return
        try:
            try:
                store.fail(key, error=error, org_id=org_id)
            except TypeError:
                store.fail(key, error=error)
        except Exception as exc:
            logger.warning("business_execution idempotency fail failed: %s", exc)


__all__ = [
    "AuditCallback",
    "ExecutionAdapter",
    "ExecutionDenied",
    "ExecutionRegistry",
    "ExecutionResult",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
]
