"""Alembic environment.

Uses a synchronous psycopg connection derived from DATABASE_URL.
All application tables live in the ``crm`` schema. The alembic version table
stays in ``public`` so a full downgrade (which drops the crm schema) works.
"""
import os
from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context
from app.models import base  # noqa: F401  (import registers metadata)
from app.models.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://")


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_sync_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS crm")
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
                include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
