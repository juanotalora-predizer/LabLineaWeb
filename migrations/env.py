"""Entorno de Alembic.

Las migraciones corren SIEMPRE con el rol dueño (lablinea_owner), nunca con el de la
aplicación (spec infraestructura/0007). La base se toma del .env; para otra base:

    alembic -x base=lablinea_test upgrade head
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Sin autogenerate: las migraciones se escriben a mano para controlar RLS, permisos y triggers.
target_metadata = None


def _url():
    base = context.get_x_argument(as_dictionary=True).get("base")
    return get_settings().url_owner(base)


def run_migrations_offline() -> None:
    context.configure(
        url=_url().render_as_string(hide_password=True),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
