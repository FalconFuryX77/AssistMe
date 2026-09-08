"""Dialect portability: PostgreSQL-first types that still work on SQLite.

AssistMe targets PostgreSQL 14+ in every deployed environment. The unit test
suite runs on SQLite because an in-process database makes tests fast and
hermetic. Those two facts pull in opposite directions: the features that make
the production schema good — ``JSONB``, native ``ENUM``, ``INET``, range types,
``EXCLUDE`` constraints — do not exist in SQLite.

The resolution used here is deliberate and worth stating, because the naive
alternatives are both bad:

* *Writing to the lowest common denominator* would throw away exactly the
  database features this system needs, to serve a test harness. Rejected.
* *Running tests only on PostgreSQL* is defensible but makes the suite slow and
  couples every contributor to a running server. Adopted **selectively**: the
  constraint, trigger, partition and isolation behaviour that cannot be
  emulated is tested against a real PostgreSQL instance (see
  ``tests/test_postgres_schema.py``, skipped when no server is configured),
  while business logic keeps running on SQLite.

So each type below compiles to the strong PostgreSQL construct and degrades to
the closest SQLite equivalent, and anything that *cannot* degrade safely is
guarded by :func:`is_postgres` rather than silently emulated.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Dialect, String, Uuid
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.types import TypeDecorator

__all__ = [
    "JSONB",
    "PortableUUID",
    "is_postgres",
    "pg_only",
]


def is_postgres(bind: Any) -> bool:
    """True when ``bind`` (engine, connection, dialect, or URL string) is PostgreSQL."""
    if bind is None:
        return False
    if isinstance(bind, str):
        return bind.startswith("postgres")
    dialect = getattr(bind, "dialect", bind)
    name = getattr(dialect, "name", "")
    return name == "postgresql"


def pg_only(connection: Connection | Engine) -> bool:
    """Guard for DDL that only exists on PostgreSQL.

    Used by migrations and DDL hooks so a SQLite test database quietly skips
    partitions, triggers, materialised views, and row-level security instead of
    failing to build at all.
    """
    return is_postgres(connection)


class JSONB(TypeDecorator):
    """``JSONB`` on PostgreSQL, ``JSON`` elsewhere.

    ``JSONB`` is not merely a nicer name for ``JSON``: it stores a decomposed
    binary form, which makes containment queries (``@>``) and GIN indexes
    possible. Every semi-structured column in this schema — model feature
    vectors, context payloads, audit detail — is queried by containment at some
    point, so ``JSONB`` is the correct choice and the ``JSON`` fallback is a
    test-only concession.
    """

    #: ``none_as_null=True`` makes a Python ``None`` store as SQL ``NULL``
    #: rather than as the JSON scalar ``null``.
    #:
    #: This is not a stylistic preference. With the default, ``col IS NULL``
    #: is false for a column set to ``None``, ``COALESCE`` does not fire, and —
    #: as this schema discovered — a ``CHECK (... OR col IS NULL)`` constraint
    #: rejects a row the application believed it had left empty. Two
    #: representations of absence in one column is a bug generator; there is
    #: only one here.
    impl = JSON(none_as_null=True)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.JSONB(none_as_null=True))
        return dialect.type_descriptor(JSON(none_as_null=True))


class PortableUUID(TypeDecorator):
    """Native ``uuid`` on PostgreSQL, ``CHAR(36)`` on SQLite, ``str`` in Python.

    PostgreSQL's native ``uuid`` stores 16 bytes and compares as an integer
    pair, against 36 bytes and a collation-aware string comparison for
    ``VARCHAR(36)``. On a schema where nearly every foreign key is a UUID, that
    is a material difference in index size and join cost — the primary-key
    index on a 10-million-row table is roughly halved.

    Python-side values stay ``str`` so that no existing service or test code
    changes: ``SQLAlchemy.Uuid(as_uuid=False)`` handles the conversion at the
    driver boundary.
    """

    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Uuid(as_uuid=False, native_uuid=True))
        return dialect.type_descriptor(String(36))
