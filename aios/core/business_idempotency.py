"""Durable DB-backed idempotency for business execution side effects.

Atomic claim: unique (scope, idempotency_key) insert. Duplicate lookups return
stored record for replay. Uses sync SQLAlchemy engine derived from app DB URL so
claim works from both sync and async call paths without event-loop bridging.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Column, DateTime, String, Text, UniqueConstraint, create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)


class _Base(DeclarativeBase):
    pass


class BusinessIdempotencyRecord(_Base):
    __tablename__ = "business_idempotency_records"
    __table_args__ = (
        UniqueConstraint("scope", "idempotency_key", name="uq_business_idempotency_scope_key"),
    )

    # scope isolates keys across orgs/environments; default "global" for compat.
    scope: str = Column(String(64), primary_key=True)
    idempotency_key: str = Column(String(128), primary_key=True)
    status: str = Column(String(20), nullable=False, default="processing")  # processing|completed|failed
    adapter: str = Column(String(64), nullable=False, default="")
    action: str = Column(String(128), nullable=False, default="")
    org_id: str | None = Column(String(64), nullable=True, index=True)
    result_json: str | None = Column(Text, nullable=True)
    error: str | None = Column(Text, nullable=True)
    created_at: datetime = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


DEFAULT_PROCESSING_TTL_SECONDS = 300


@dataclass
class IdempotencyClaimRecord:
    key: str
    scope: str
    status: str
    adapter: str = ""
    action: str = ""
    org_id: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    processing_age_seconds: float | None = None
    stale_processing: bool = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sync_database_url(url: str) -> str:
    u = str(url or "").strip()
    if not u:
        return u
    # sqlite+aiosqlite:///./x -> sqlite:///./x
    if u.startswith("sqlite+aiosqlite"):
        return u.replace("sqlite+aiosqlite", "sqlite", 1)
    # postgresql+asyncpg:// -> postgresql+psycopg:// (psycopg3) fallback postgresql://
    if u.startswith("postgresql+asyncpg"):
        return u.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    if u.startswith("postgres+asyncpg"):
        return u.replace("postgres+asyncpg", "postgresql+psycopg", 1)
    return u


def _scope_for(key: str, org_id: str | None = None) -> str:
    # Org-scoped when org_id known; else global scope preserves old behavior.
    org = str(org_id or "").strip()
    if org:
        return f"org:{org}"
    return "global"


class DBIdempotencyStore:
    """DB-backed idempotency store with atomic claim semantics.

    claim() is atomic via unique insert. On duplicate, lookup returns stored
    record for replay. Compatible with ExecutionRegistry idempotency hooks.
    """

    def __init__(
        self,
        *,
        database_url: str | None = None,
        engine: Any = None,
        scope: str = "global",
        processing_ttl_seconds: int = DEFAULT_PROCESSING_TTL_SECONDS,
    ) -> None:
        self.scope = str(scope or "global")
        self._lock = threading.Lock()
        self._engine = engine
        self._session_factory: sessionmaker[Session] | None = None
        self._database_url = database_url
        self._init_error: str | None = None
        try:
            ttl = int(processing_ttl_seconds)
        except Exception:
            ttl = DEFAULT_PROCESSING_TTL_SECONDS
        self.processing_ttl_seconds = max(1, ttl)
        if self._engine is not None:
            self._session_factory = sessionmaker(self._engine, expire_on_commit=False)
        elif self._database_url:
            self._ensure_ready()

    @classmethod
    def from_settings(cls, settings: Any = None) -> "DBIdempotencyStore | None":
        try:
            if settings is None:
                from aios.config import settings as app_settings

                settings = app_settings
            url = str(getattr(settings, "database_url", "") or "").strip()
            if not url:
                return None
            ttl = getattr(settings, "business_idempotency_processing_ttl_seconds", DEFAULT_PROCESSING_TTL_SECONDS)
            store = cls(database_url=url, processing_ttl_seconds=ttl)
            store._ensure_ready()
            if store._init_error:
                logger.warning("DBIdempotencyStore unavailable: %s", store._init_error)
                return None
            return store
        except Exception as e:
            logger.warning("DBIdempotencyStore init failed: %s", e)
            return None

    def _ensure_ready(self) -> bool:
        if self._session_factory is not None:
            return True
        if self._init_error:
            return False
        with self._lock:
            if self._session_factory is not None:
                return True
            if self._init_error:
                return False
            url = _sync_database_url(str(self._database_url or ""))
            if not url:
                self._init_error = "missing database_url"
                return False
            try:
                connect_args: dict[str, Any] = {}
                if url.startswith("sqlite"):
                    connect_args["check_same_thread"] = False
                self._engine = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)
                # verify connectivity / driver
                with self._engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                BusinessIdempotencyRecord.__table__.create(bind=self._engine, checkfirst=True)
                self._session_factory = sessionmaker(self._engine, expire_on_commit=False)
                return True
            except Exception as e:
                self._init_error = str(e)
                logger.warning("DBIdempotencyStore init error: %s", e)
                return False

    def _session(self) -> Session:
        if not self._ensure_ready() or self._session_factory is None:
            raise RuntimeError(self._init_error or "idempotency store unavailable")
        return self._session_factory()

    def _normalize_key(self, key: str) -> str:
        return str(key or "").strip()

    def _resolve_scope(self, key: str, org_id: str | None, scope: str | None) -> str:
        if scope:
            return str(scope).strip() or "global"
        if org_id:
            return _scope_for(key, org_id)
        return str(self.scope or "global").strip() or "global"

    @staticmethod
    def _as_utc(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _record_from_row(
        self,
        row: BusinessIdempotencyRecord,
        *,
        now: datetime | None = None,
    ) -> IdempotencyClaimRecord:
        result = None
        if row.result_json:
            try:
                result = json.loads(row.result_json)
            except Exception:
                result = {"raw": row.result_json}
        ref_now = self._as_utc(now) or _utcnow()
        updated = self._as_utc(row.updated_at) or self._as_utc(row.created_at) or ref_now
        age = max(0.0, (ref_now - updated).total_seconds())
        stale = bool(row.status == "processing" and age >= float(self.processing_ttl_seconds))
        return IdempotencyClaimRecord(
            key=row.idempotency_key,
            scope=row.scope,
            status=row.status,
            adapter=row.adapter or "",
            action=row.action or "",
            org_id=row.org_id,
            result=result,
            error=row.error,
            created_at=self._as_utc(row.created_at),
            updated_at=updated,
            processing_age_seconds=age if row.status == "processing" else None,
            stale_processing=stale,
        )

    def claim(
        self,
        key: str,
        *,
        org_id: str | None = None,
        adapter: str = "",
        action: str = "",
        scope: str | None = None,
    ) -> bool:
        k = self._normalize_key(key)
        if not k:
            return False
        sc = self._resolve_scope(k, org_id, scope)
        now = _utcnow()
        with self._session() as s:
            try:
                rec = BusinessIdempotencyRecord(
                    scope=sc,
                    idempotency_key=k,
                    status="processing",
                    adapter=str(adapter or ""),
                    action=str(action or ""),
                    org_id=str(org_id).strip() if org_id else None,
                    created_at=now,
                    updated_at=now,
                )
                s.add(rec)
                s.commit()
                return True
            except IntegrityError:
                s.rollback()
                return False

    def get(
        self,
        key: str,
        *,
        org_id: str | None = None,
        scope: str | None = None,
        now: datetime | None = None,
    ) -> IdempotencyClaimRecord | None:
        k = self._normalize_key(key)
        if not k:
            return None
        sc = self._resolve_scope(k, org_id, scope)
        with self._session() as s:
            row = s.get(BusinessIdempotencyRecord, {"scope": sc, "idempotency_key": k})
            if row is None:
                return None
            return self._record_from_row(row, now=now)

    def complete(
        self,
        key: str,
        *,
        result: dict[str, Any] | None = None,
        org_id: str | None = None,
        scope: str | None = None,
    ) -> None:
        k = self._normalize_key(key)
        if not k:
            return
        sc = self._resolve_scope(k, org_id, scope)
        with self._session() as s:
            row = s.get(BusinessIdempotencyRecord, {"scope": sc, "idempotency_key": k})
            if row is None:
                return
            row.status = "completed"
            row.result_json = json.dumps(result or {}, ensure_ascii=False, default=str)
            row.error = None
            row.updated_at = _utcnow()
            s.commit()

    def fail(
        self,
        key: str,
        *,
        error: str = "",
        result: dict[str, Any] | None = None,
        org_id: str | None = None,
        scope: str | None = None,
    ) -> None:
        k = self._normalize_key(key)
        if not k:
            return
        sc = self._resolve_scope(k, org_id, scope)
        with self._session() as s:
            row = s.get(BusinessIdempotencyRecord, {"scope": sc, "idempotency_key": k})
            if row is None:
                return
            row.status = "failed"
            row.error = str(error or "")[:4000]
            if result is not None:
                row.result_json = json.dumps(result, ensure_ascii=False, default=str)
            row.updated_at = _utcnow()
            s.commit()

    def reclaim_stale_processing(
        self,
        *,
        scope: str | None = None,
        org_id: str | None = None,
        older_than_seconds: int | None = None,
        limit: int = 100,
        now: datetime | None = None,
        error: str = "stale processing claim reclaimed; no side effect re-executed",
    ) -> dict[str, Any]:
        """Mark stale `processing` claims as `failed` (reclaimable) atomically.

        Fail-closed: never re-executes side effects. Ops/test can call before retry.
        Retry after reclaim requires a NEW idempotency key; same key stays duplicate-failed.
        """
        if not self._ensure_ready():
            raise RuntimeError(self._init_error or "idempotency store unavailable")
        ttl = self.processing_ttl_seconds if older_than_seconds is None else max(1, int(older_than_seconds))
        ref_now = self._as_utc(now) or _utcnow()
        cutoff = ref_now - timedelta(seconds=ttl)
        limit_n = max(1, min(int(limit or 100), 1000))
        reclaimed: list[dict[str, Any]] = []
        with self._session() as s:
            # Python-side age filter avoids sqlite naive/aware datetime comparison quirks.
            q = select(BusinessIdempotencyRecord).where(BusinessIdempotencyRecord.status == "processing")
            if scope:
                q = q.where(BusinessIdempotencyRecord.scope == str(scope).strip())
            if org_id:
                q = q.where(BusinessIdempotencyRecord.org_id == str(org_id).strip())
            rows = s.execute(q.order_by(BusinessIdempotencyRecord.updated_at.asc()).limit(limit_n * 5)).scalars().all()
            for row in rows:
                if len(reclaimed) >= limit_n:
                    break
                fresh = s.get(
                    BusinessIdempotencyRecord,
                    {"scope": row.scope, "idempotency_key": row.idempotency_key},
                )
                if fresh is None or fresh.status != "processing":
                    continue
                updated = self._as_utc(fresh.updated_at) or self._as_utc(fresh.created_at) or ref_now
                if updated >= cutoff:
                    continue
                age = max(0.0, (ref_now - updated).total_seconds())
                existing = {}
                if fresh.result_json:
                    try:
                        parsed = json.loads(fresh.result_json)
                        if isinstance(parsed, dict):
                            existing = parsed
                    except Exception:
                        existing = {"raw": fresh.result_json}
                fresh.status = "failed"
                fresh.error = str(error)[:4000]
                fresh.result_json = json.dumps(
                    {
                        **existing,
                        "reclaimed_stale_processing": True,
                        "stale_processing": True,
                        "processing_ttl_seconds": ttl,
                        "processing_age_seconds": age,
                        "reclaimed_at": ref_now.isoformat(),
                    },
                    ensure_ascii=False,
                    default=str,
                )
                fresh.updated_at = ref_now
                reclaimed.append(
                    {
                        "scope": fresh.scope,
                        "idempotency_key": fresh.idempotency_key,
                        "org_id": fresh.org_id,
                        "adapter": fresh.adapter,
                        "action": fresh.action,
                        "processing_age_seconds": age,
                    }
                )
            if reclaimed:
                s.commit()
        return {
            "ok": True,
            "reclaimed": len(reclaimed),
            "processing_ttl_seconds": ttl,
            "cutoff": cutoff.isoformat(),
            "items": reclaimed,
        }

    @property
    def durable(self) -> bool:
        return self._ensure_ready()


__all__ = [
    "BusinessIdempotencyRecord",
    "DBIdempotencyStore",
    "DEFAULT_PROCESSING_TTL_SECONDS",
    "IdempotencyClaimRecord",
]
