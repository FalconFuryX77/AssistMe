"""Alembic environment using the same runtime database configuration as API."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from core.config import settings
from core.database import Base
import models  # noqa: F401 - register every model with Base.metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

sync_database_url = (
    settings.DATABASE_URL.replace("+asyncpg", "+psycopg")
    .replace("+aiosqlite", "")
)
config.set_main_option("sqlalchemy.url", sync_database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=sync_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        {"sqlalchemy.url": sync_database_url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
