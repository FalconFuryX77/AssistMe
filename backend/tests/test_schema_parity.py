"""The migration chain and the ORM must produce the same schema.

Why this exists
---------------
There are two ways this project can build a database:

* ``alembic upgrade head`` — what production does.
* ``Base.metadata.create_all`` — what development and the test suite do.

They are written separately, so they *will* drift, and the drift is silent: the
tests pass on an ORM-built database while production runs a schema that differs.
This project has already been bitten by exactly that. The inherited
``create_tables()`` added two columns via ``try/except ALTER TABLE``, so
``device_accounts.device_secret_hash`` and ``device_pairings.failed_attempts``
existed in every running database and in no migration. Nothing reported it,
because the exception was swallowed.

Writing this migration surfaced a second instance: the models declared native
enums for eleven columns that the migration was leaving as ``VARCHAR``.

These tests compare the two schemas column by column and constraint by
constraint. They are skipped without ``TEST_DATABASE_URL``, because the
comparison is only meaningful on PostgreSQL — SQLite has neither native enums
nor most of what would differ.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not set; schema parity requires PostgreSQL",
)

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _sync_url(url: str) -> str:
    return url.replace("+asyncpg", "+psycopg").replace("+aiosqlite", "")


def _database_name(url: str, suffix: str) -> str:
    base = url.rsplit("/", 1)[-1].split("?")[0]
    return f"{base}_{suffix}"


def _admin_url(url: str) -> str:
    return _sync_url(url).rsplit("/", 1)[0] + "/postgres"


def _recreate(name: str) -> None:
    engine = create_engine(_admin_url(TEST_DATABASE_URL), isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine.dispose()


def _url_for(name: str) -> str:
    return _sync_url(TEST_DATABASE_URL).rsplit("/", 1)[0] + f"/{name}"


def _introspect(url: str) -> dict:
    """Read back the schema as comparable plain data."""
    engine = create_engine(url)
    schema: dict = {"columns": {}, "checks": {}, "indexes": {}, "enums": {}}

    with engine.connect() as conn:
        for table, column, data_type, udt, nullable in conn.execute(
            text(
                "SELECT table_name, column_name, data_type, udt_name, is_nullable"
                "  FROM information_schema.columns"
                " WHERE table_schema = 'public'"
                "   AND table_name <> 'alembic_version'"
                "   AND table_name NOT LIKE '%\\_p2%'"
                "   AND table_name NOT LIKE '%\\_default'"
            )
        ):
            schema["columns"][f"{table}.{column}"] = (data_type, udt, nullable)

        for name, definition in conn.execute(
            text(
                "SELECT con.conname, pg_get_constraintdef(con.oid)"
                "  FROM pg_constraint con"
                "  JOIN pg_class c ON c.oid = con.conrelid"
                " WHERE con.contype = 'c'"
                "   AND con.connamespace = 'public'::regnamespace"
                "   AND NOT EXISTS (SELECT 1 FROM pg_inherits i WHERE i.inhrelid = c.oid)"
            )
        ):
            schema["checks"][name] = " ".join(definition.split())

        for name, definition in conn.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes"
                " WHERE schemaname = 'public'"
                # Alembic's own bookkeeping table is not part of the
                # application schema and exists only in the migrated database.
                "   AND tablename <> 'alembic_version'"
                "   AND tablename NOT LIKE '%\\_p2%'"
                "   AND tablename NOT LIKE '%\\_default'"
            )
        ):
            schema["indexes"][name] = " ".join(definition.split())

        for name, label in conn.execute(
            text(
                "SELECT t.typname, e.enumlabel FROM pg_type t"
                "  JOIN pg_enum e ON e.enumtypid = t.oid"
                "  JOIN pg_namespace n ON n.oid = t.typnamespace"
                " WHERE n.nspname = 'public' ORDER BY t.typname, e.enumsortorder"
            )
        ):
            schema["enums"].setdefault(name, []).append(label)

    engine.dispose()
    return schema


@pytest.fixture(scope="module")
def schemas() -> tuple[dict, dict]:
    """Build one database each way and introspect both."""
    migrated_name = _database_name(TEST_DATABASE_URL, "migrated")
    orm_name = _database_name(TEST_DATABASE_URL, "orm")

    _recreate(migrated_name)
    _recreate(orm_name)

    env = dict(os.environ)
    env["DATABASE_URL"] = _url_for(migrated_name)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"alembic upgrade failed:\n{result.stderr[-3000:]}"

    build = (
        "import asyncio, os;"
        "from core.database import create_tables;"
        "asyncio.run(create_tables())"
    )
    env_orm = dict(os.environ)
    env_orm["DATABASE_URL"] = _url_for(orm_name).replace("+psycopg", "+asyncpg")
    result = subprocess.run(
        [sys.executable, "-c", build],
        cwd=BACKEND_DIR,
        env=env_orm,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"create_tables failed:\n{result.stderr[-3000:]}"

    return _introspect(_url_for(migrated_name)), _introspect(_url_for(orm_name))


def test_same_tables_and_columns(schemas) -> None:
    """Every column must exist in both, with the same type and nullability."""
    migrated, orm = schemas

    only_migrated = set(migrated["columns"]) - set(orm["columns"])
    only_orm = set(orm["columns"]) - set(migrated["columns"])

    assert not only_migrated, (
        "columns the migration creates but the ORM does not: "
        f"{sorted(only_migrated)}"
    )
    assert not only_orm, (
        "columns the ORM creates but the migration does not — a production "
        f"database would be missing these: {sorted(only_orm)}"
    )

    mismatched = {
        name: (migrated["columns"][name], orm["columns"][name])
        for name in migrated["columns"]
        if migrated["columns"][name] != orm["columns"][name]
    }
    assert not mismatched, f"column type or nullability differs: {mismatched}"


def test_same_enum_types(schemas) -> None:
    """Enum types and their value orders must match.

    This is the check that catches the drift found while writing the migration:
    the models declared native enums for eleven columns that the migration was
    creating as VARCHAR, so a migration-built production database had none of
    the domain enforcement the models promised.
    """
    migrated, orm = schemas
    assert migrated["enums"] == orm["enums"], (
        "enum types differ.\n"
        f"  only in migration: {sorted(set(migrated['enums']) - set(orm['enums']))}\n"
        f"  only in ORM:       {sorted(set(orm['enums']) - set(migrated['enums']))}"
    )


def test_same_check_constraints(schemas) -> None:
    """Constraint names and definitions must match.

    Names matter as much as definitions: Alembic drops constraints by name, so
    a constraint that exists under a different name in production is one a
    future migration cannot remove.
    """
    migrated, orm = schemas

    only_migrated = set(migrated["checks"]) - set(orm["checks"])
    only_orm = set(orm["checks"]) - set(migrated["checks"])

    assert not only_orm, (
        "constraints the ORM declares that a migrated database would lack — "
        f"production would accept data the tests reject: {sorted(only_orm)}"
    )
    assert not only_migrated, (
        f"constraints only the migration creates: {sorted(only_migrated)}"
    )


def test_same_indexes(schemas) -> None:
    """Index names and definitions must match, including partial predicates."""
    migrated, orm = schemas

    only_migrated = set(migrated["indexes"]) - set(orm["indexes"])
    only_orm = set(orm["indexes"]) - set(migrated["indexes"])

    assert not only_orm, f"indexes missing from a migrated database: {sorted(only_orm)}"
    assert not only_migrated, f"indexes only the migration creates: {sorted(only_migrated)}"

    differing = {
        name: (migrated["indexes"][name], orm["indexes"][name])
        for name in migrated["indexes"]
        if migrated["indexes"][name] != orm["indexes"][name]
    }
    assert not differing, f"index definitions differ: {differing}"
