"""Database backend abstraction — Supabase (SQLAlchemy) primary, Convex failover.

Usage:
    from aios.db.backend import db_session, get_db_backend

    # FastAPI dependency
    db: DatabaseBackend = Depends(get_db_backend)
    result = await db.execute(select(Model).where(...))

    # Direct usage in background tasks
    async with db_session() as db:
        result = await db.get(Model, id)

Pattern follows aios/channels/base.py ABC + registry.
"""

import logging
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from aios.config import settings

logger = logging.getLogger(__name__)

# ─── ABC ───


class DatabaseBackend(ABC):
    """Abstract database backend. Implementations: SQLAlchemyBackend, ConvexBackend."""

    @abstractmethod
    async def get(self, model: type, ident: Any) -> Any | None: ...

    @abstractmethod
    async def execute(self, stmt) -> Any:
        """Execute a statement (SQLAlchemy select/update/delete or Convex equivalent)."""

    @abstractmethod
    def add(self, obj) -> None: ...


    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def delete(self, obj) -> None: ...

    @abstractmethod
    async def flush(self) -> None: ...

    @abstractmethod
    async def refresh(self, obj) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def health(self) -> bool:
        """Check backend connectivity. Used for failover detection."""


# ─── Registry + failover ───


class BackendRegistry:
    """Holds primary + replica backends and handles failover."""

    def __init__(self):
        self._primary: DatabaseBackend | None = None
        self._replica: DatabaseBackend | None = None
        self._active: DatabaseBackend | None = None
        self._failed_over = False
        self._primary_type = "sqlalchemy"
        self._replica_type = ""

    def init(self, primary: DatabaseBackend, replica: DatabaseBackend | None = None):
        self._primary = primary
        self._replica = replica
        self._active = primary
        logger.info("Backend primary=%s replica=%s", type(primary).__name__,
                    type(replica).__name__ if replica else "none")

    async def check_failover(self) -> bool:
        """Check primary health. If primary down and replica exists, switch.
        Returns True if active backend changed."""
        if not self._active:
            return False
        if not await self._active.health():
            if self._replica and not self._failed_over:
                logger.warning("Primary backend unhealthy — failing over to replica")
                self._active = self._replica
                self._failed_over = True
                return True
            elif self._replica and self._failed_over and self._active is self._replica:
                # check if primary recovered
                if await self._primary.health():
                    logger.info("Primary backend recovered — switching back")
                    self._active = self._primary
                    self._failed_over = False
                    return True
        return False

    @property
    def active(self) -> DatabaseBackend | None:
        return self._active

    @property
    def is_failed_over(self) -> bool:
        return self._failed_over

    async def close_all(self):
        for b in (self._primary, self._replica):
            if b:
                await b.close()

    def summary(self) -> dict:
        return {
            "active": type(self._active).__name__ if self._active else "none",
            "primary": type(self._primary).__name__ if self._primary else "none",
            "replica": type(self._replica).__name__ if self._replica else "none",
            "failed_over": self._failed_over,
        }


registry = BackendRegistry()


def _fresh_backend() -> DatabaseBackend | None:
    """Create fresh backend with its own session.

    Uses settings.db_backend to determine type. Each call gets
    independent session so concurrent requests never share txn state.
    """
    if not settings.db_backend:
        return None
    return _create_backend(settings.db_backend)


# ─── Factory ───


def _create_backend(backend_type: str) -> DatabaseBackend:
    """Create a backend by type name."""
    if backend_type == "sqlalchemy":
        from aios.db.backends.sqlalchemy_backend import SQLAlchemyBackend
        return SQLAlchemyBackend()
    elif backend_type == "convex":
        from aios.db.backends.convex_backend import ConvexBackend
        return ConvexBackend(settings.convex_url, settings.convex_admin_key)
    else:
        raise ValueError(f"Unknown backend type: {backend_type}")


async def init_backends():
    """Initialize primary + optional replica backends. Call on startup."""
    primary = _create_backend(settings.db_backend)
    replica = None
    if settings.db_replica_backend:
        replica = _create_backend(settings.db_replica_backend)
    registry.init(primary, replica)
    logger.info("Database backends initialized")


# ─── Session accessor ───


@asynccontextmanager
async def db_session() -> AsyncGenerator[DatabaseBackend, None]:
    """Context manager yielding a fresh backend with dedicated session per call.

    Each async with creates a new SQLAlchemy session (or Convex client call).
    Safe for concurrent use — no shared session state.
    """
    backend = _fresh_backend()
    if not backend:
        raise RuntimeError("Database backend not initialized. Call init_backends() on startup.")
    try:
        yield backend
    finally:
        await backend.close()


async def get_db_backend() -> AsyncGenerator[DatabaseBackend, None]:
    """FastAPI dependency — fresh backend with dedicated session per request."""
    backend = _fresh_backend()
    if not backend:
        raise RuntimeError("Database backend not initialized. Call init_backends() on startup.")
    try:
        yield backend
    finally:
        await backend.close()
