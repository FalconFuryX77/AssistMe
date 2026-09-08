"""SQLAlchemy async engine, session factory, and declarative Base.

What changed and why
--------------------
The inherited ``create_tables()`` ended with two blocks of the form::

    try:
        await conn.execute(text("ALTER TABLE ... ADD COLUMN ..."))
    except Exception:
        pass

That is schema migration by swallowed exception. It cannot tell "the column
already exists" (fine) from "the ALTER failed because the table is locked, the
type is wrong, or the database is a different one than expected" (not fine), and
it leaves no record of which statements ran. Those statements are now proper
Alembic revisions, and this module's development bootstrap does one thing:
create the ORM's tables, plus — on PostgreSQL — the DDL objects the ORM cannot
express.

Connection pooling is also configured properly for an async workload; see
:func:`_engine_options` for the reasoning behind each value.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from core.config import settings
from core.db.ddl import metadata_with_naming_convention

logger = logging.getLogger(__name__)


def _engine_options() -> dict:
    """Engine options appropriate to the configured backend."""
    options: dict = {
        "echo": settings.DB_ECHO,
        # Reduce per-statement overhead on PostgreSQL by caching server-side
        # prepared statements. Bounded, because an unbounded cache leaks
        # memory across the many distinct statements an ORM generates.
        "pool_pre_ping": True,
    }

    if settings.DATABASE_URL.startswith("sqlite"):
        # SQLite in tests: a shared in-memory or file database with a real pool
        # invites "database is locked" under concurrent async tasks, and the
        # pool buys nothing when connections are essentially free.
        options["poolclass"] = NullPool
        return options

    options.update(
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
        # Recycle below typical proxy and firewall idle timeouts (often 300 s
        # on managed PostgreSQL), so the application closes stale connections
        # itself rather than discovering them mid-request.
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
    )
    return options


engine = create_async_engine(settings.DATABASE_URL, **_engine_options())

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models.

    Carries the shared naming convention so every constraint and index has a
    deterministic name; see :data:`core.db.ddl.NAMING_CONVENTION`.
    """

    metadata = metadata_with_naming_convention()


# ----------------------------------------------------------------------
# SQLite pragmas
# ----------------------------------------------------------------------


@event.listens_for(engine.sync_engine, "connect")
def _configure_sqlite(dbapi_connection, connection_record) -> None:
    """Enable the SQLite behaviour the test suite needs to match production.

    SQLite disables foreign key enforcement by default. Without this pragma the
    test suite silently accepts orphaned rows that PostgreSQL would reject —
    the worst kind of dialect divergence, because it makes tests pass on data
    production would refuse.
    """
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL allows a reader concurrent with a writer, which matters for the
        # async tests that hold a read open across an await.
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


# ----------------------------------------------------------------------
# Bootstrap
# ----------------------------------------------------------------------


async def create_tables(bind_engine=None) -> None:
    """Create ORM tables, and on PostgreSQL the DDL the ORM cannot express.

    Development and test convenience only. Production schema changes go through
    Alembic (``alembic upgrade head``); ``AUTO_CREATE_TABLES`` defaults to false
    whenever ``APP_ENV`` is production.
    """
    from core.db.ddl import (
        APPEND_ONLY_GUARD,
        AUDIT_CHAIN,
        EXCLUSION_CONSTRAINTS,
        MATERIALIZED_VIEWS,
        PARTITION_HELPERS,
        ROW_LEVEL_SECURITY,
        UPDATED_AT_TRIGGER,
        attach_append_only,
        attach_audit_chain,
        attach_updated_at,
        split_sql_script,
    )
    from core.db.dialect import is_postgres

    # Importing the models package is what populates ``Base.metadata``. Doing
    # it here rather than relying on the caller means ``create_tables()``
    # cannot silently create nothing because of import order — which is a
    # failure that looks exactly like success.
    import models  # noqa: F401  (registers every mapper)

    if not Base.metadata.tables:  # pragma: no cover - defensive
        raise RuntimeError(
            "No tables registered on Base.metadata; models failed to import."
        )

    target_engine = bind_engine or engine
    async with target_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        if not is_postgres(conn):
            logger.info(
                "SQLite bootstrap complete: partitions, triggers, materialised "
                "views and RLS are PostgreSQL-only and were skipped."
            )
            return

        scripts = [
            block["up"]
            for block in (
                UPDATED_AT_TRIGGER,
                AUDIT_CHAIN,
                APPEND_ONLY_GUARD,
                PARTITION_HELPERS,
            )
        ]
        scripts += [
            attach_updated_at(table)
            for table in (
                "users",
                "sessions",
                "trusted_contacts",
                "trusted_devices",
                "policy_decisions",
                "context_snapshots",
            )
        ]
        scripts.append(attach_audit_chain("audit_ledger"))
        scripts += [
            attach_append_only(table) for table in ("audit_ledger", "context_events")
        ]

        for script in scripts:
            for statement in split_sql_script(script):
                await conn.execute(text(statement))

        # A partitioned parent can hold no rows itself, so the current and next
        # few months must exist before the first insert. Provisioning ahead
        # means a month boundary at 00:00 does not become an outage.
        for parent in ("audit_ledger", "context_events", "ml_decision_log"):
            await conn.execute(
                text("SELECT assistme_provision_partitions(:parent, 3, 1)"),
                {"parent": parent},
            )
            # Safety net for a row whose timestamp falls outside every
            # provisioned range. See core.db.ddl for why it should stay empty.
            await conn.execute(
                text("SELECT assistme_ensure_default_partition(:parent)"),
                {"parent": parent},
            )

        # Exclusion constraints, analytics views, and RLS come last: they
        # depend on the base tables and on the partitions existing.
        for block in (EXCLUSION_CONSTRAINTS, MATERIALIZED_VIEWS, ROW_LEVEL_SECURITY):
            for statement in split_sql_script(block["up"]):
                await conn.execute(text(statement))

        logger.info(
            "PostgreSQL bootstrap complete "
            "(triggers, partitions, exclusion constraints, views, RLS)."
        )


async def check_database_connection() -> None:
    """Raise if the database is unavailable; used by readiness probes."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


# ----------------------------------------------------------------------
# Session dependencies
# ----------------------------------------------------------------------


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a database session.

    Rolls back on an unhandled exception before closing. Without the explicit
    rollback, a failed request can return its connection to the pool with an
    open transaction, and the next request to borrow it inherits that state —
    a genuinely confusing class of cross-request bug.
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def session_scope(user_id: str | None = None) -> AsyncIterator[AsyncSession]:
    """A transactional session, optionally identified for row-level security.

    When ``user_id`` is supplied and the backend is PostgreSQL, the session sets
    ``assistme.current_user_id`` for the duration of the transaction, which is
    what the RLS policies in :data:`core.db.ddl.ROW_LEVEL_SECURITY` read.

    ``set_config(..., true)`` scopes the setting to the transaction, so it is
    cleared automatically at commit or rollback and cannot leak to the next
    borrower of a pooled connection — which, if it did, would attribute one
    user's queries to another.
    """
    from core.db.dialect import is_postgres

    async with async_session_factory() as session:
        try:
            if user_id and is_postgres(session.bind):
                await session.execute(
                    text("SELECT set_config('assistme.current_user_id', :uid, true)"),
                    {"uid": str(user_id)},
                )
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
