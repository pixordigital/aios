"""Alembic env — async SQLAlchemy for Postgres/SQLite."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from aios.config import settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# override URL from settings (reads env)
config.set_main_option("sqlalchemy.url", settings.database_url)

from aios.db.models import Base  # noqa: E402
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    is_postgres = "postgresql" in url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        version_table="alembic_version_aios" if is_postgres else "alembic_version",
        version_table_schema="aios" if is_postgres else None,
    )
    with context.begin_transaction():
        if is_postgres:
            context.execute("CREATE SCHEMA IF NOT EXISTS aios")
            context.execute("SET LOCAL search_path TO aios, public, extensions")
        context.run_migrations()


def do_run_migrations(connection):
    is_sqlite = connection.dialect.name == "sqlite"
    if not is_sqlite:
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS aios")
        connection.commit()
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=is_sqlite,  # batch mode for SQLite ALTER TABLE support
        version_table="alembic_version" if is_sqlite else "alembic_version_aios",
        version_table_schema=None if is_sqlite else "aios",
    )
    with context.begin_transaction():
        if not is_sqlite:
            connection.exec_driver_sql("SET LOCAL search_path TO aios, public, extensions")
        context.run_migrations()


async def run_async_migrations() -> None:
    connect_args = {}
    if "postgresql" in settings.database_url:
        connect_args["server_settings"] = {"search_path": "aios, public, extensions"}
    connectable = create_async_engine(
        settings.database_url, poolclass=pool.NullPool,
        connect_args=connect_args,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
