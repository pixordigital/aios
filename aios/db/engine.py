from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from aios.config import settings


def _is_postgres() -> bool:
    return "postgresql" in settings.database_url


def _is_sqlite() -> bool:
    return "sqlite" in settings.database_url


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size if _is_postgres() else None,
    max_overflow=settings.db_max_overflow if _is_postgres() else None,
    connect_args={} if not _is_postgres() else {},
)


class Base(DeclarativeBase):
    pass


async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    async with engine.begin() as conn:
        from aios.db import models  # noqa: F401
        # Ensure schema exists if using PostgreSQL with a specific schema
        if _is_postgres():
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS aios"))
        await conn.run_sync(Base.metadata.create_all)
