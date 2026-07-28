"""SQLAlchemy backend — wraps AsyncSession for SQLite + Supabase Postgres.

Each backend instance gets its own session from the global sessionmaker.
Safe for concurrent request handling — no shared state.
"""

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from aios.db.backend import DatabaseBackend
from aios.db.engine import async_session

logger = logging.getLogger(__name__)


class SQLAlchemyBackend(DatabaseBackend):
    """Delegates all calls to a dedicated AsyncSession.

    Works with SQLite (dev) and PostgreSQL/Supabase (production).
    Each instance creates its own session — never shared across requests.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session: AsyncSession | None = session

    async def _sess(self) -> AsyncSession:
        if self._session is None:
            self._session = async_session()
        return self._session

    async def get(self, model: type, ident: Any) -> Any | None:
        s = await self._sess()
        return await s.get(model, ident)

    async def execute(self, stmt) -> Any:
        s = await self._sess()
        return await s.execute(stmt)

    def add(self, obj) -> None:
        if self._session is None:
            self._session = async_session()
        self._session.add(obj)

    async def commit(self) -> None:
        s = await self._sess()
        await s.commit()

    async def delete(self, obj) -> None:
        s = await self._sess()
        await s.delete(obj)

    async def flush(self) -> None:
        s = await self._sess()
        await s.flush()

    async def refresh(self, obj) -> None:
        s = await self._sess()
        await s.refresh(obj)

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def health(self) -> bool:
        try:
            s = await self._sess()
            await s.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.warning("SQLAlchemy health check failed: %s", e)
            return False
