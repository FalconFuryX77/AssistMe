"""Database infrastructure: dialect portability, domain enums, and raw DDL.

* :mod:`core.db.dialect` — types that compile to strong PostgreSQL constructs
  and degrade safely on the SQLite test dialect.
* :mod:`core.db.enums` — categorical domains enforced by the database.
* :mod:`core.db.ddl` — triggers, partitioning, materialised views, and RLS.

See ``docs/DATABASE_DESIGN.md`` for the normalisation analysis and the
rationale behind each physical-design decision.
"""

from core.db.dialect import JSONB, PortableUUID, is_postgres, pg_only

__all__ = ["JSONB", "PortableUUID", "is_postgres", "pg_only"]
