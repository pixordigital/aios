from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from aios.config import settings

_use_schema = "aios" if "postgresql" in settings.database_url else None

if _use_schema:
    # set default schema on engine connect
    engine = create_async_engine(
        settings.database_url, echo=settings.debug,
        connect_args={"server_settings": {"search_path": _use_schema}},
    )
else:
    engine = create_async_engine(settings.database_url, echo=settings.debug)


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
        await conn.run_sync(Base.metadata.create_all)
