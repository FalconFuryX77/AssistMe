"""Tamper-evident, append-only audit ledger.

Why replace ``audit_logs``
--------------------------
The inherited ``audit_logs`` table is an ordinary heap. Any role with ``UPDATE``
or ``DELETE`` on it — the application role included — can silently rewrite the
record of what a helper did on an elderly person's phone. For a product whose
security argument is "the helpee is protected by always being able to see what
happened", an editable audit trail is not a minor gap; it invalidates the claim.

This table replaces it with a ledger that has three properties:

**Append-only.** ``BEFORE UPDATE OR DELETE`` triggers raise an exception, so the
invariant holds even against the table owner and survives a misconfigured
``GRANT``.

**Tamper-evident.** Entries form a per-session hash chain,
``entry_hash(n) = SHA256(entry_hash(n-1) ‖ payload(n))``. Editing any historical
row invalidates every link after it, and ``assistme_audit_verify(session_id)``
recomputes the chain inside the database and reports the first divergence.
Detection does not depend on trusting the application that wrote the rows.

**Bounded in cost.** The table is range-partitioned by month, so retention is a
``DROP TABLE`` rather than a mass ``DELETE``, and every time-windowed query
prunes to the partitions it needs.

Two-level verification, and why
-------------------------------
The chain is verified at two levels because a single level cannot cover both
threats without a fragile cross-language contract.

*Structural* verification runs in PostgreSQL
(``assistme_audit_verify(session_id)``) and checks linkage: that every
``prev_hash`` equals the preceding ``entry_hash``, that sequence numbers have no
gaps, and that ``entry_hash = SHA256(prev_hash ‖ payload_digest ‖ seq)``. This
catches insertion, deletion, reordering, and any attempt to rewrite a hash.

*Content* verification runs in Python
(``AuditLedgerService.verify_chain``) and additionally recomputes
``payload_digest`` from the row's own fields, catching edits to ``detail``,
``event_type``, or ``actor_user_id``.

The split exists because ``payload_digest`` covers a canonically serialised JSON
payload, and PostgreSQL's ``jsonb`` text output is not byte-identical to
Python's canonical form. Rather than pretend two independent serialisers agree —
a bug waiting to happen the first time a key ordering or float format differs —
the digest is computed once, by the writer, and the database verifies everything
that does not require re-serialising it. Both levels are cheap and they compose:
structural tampering is caught without trusting the application, content
tampering is caught by the application, and the append-only trigger means an
attacker must first defeat the database to attempt either.

A documented limitation
-----------------------
``(session_id, seq)`` is logically unique, but PostgreSQL requires the partition
key to appear in every unique index on a partitioned table. Uniqueness is
therefore enforced by the append trigger, which serialises per session with
``pg_advisory_xact_lock`` before computing the next sequence number, rather than
by an index; any violation that did occur surfaces as a sequence gap during
verification. This is a real trade-off of range partitioning and is stated
rather than hidden. Hash partitioning by ``session_id`` would permit the unique
index but would forfeit time-based retention and pruning, which matter more for
a table whose dominant access pattern is "the last 30 days".
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    LargeBinary,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base
from core.db.dialect import JSONB, PortableUUID
from core.db.enums import audit_category_enum


class AuditLedgerEntry(Base):
    """One immutable, hash-chained audit record."""

    __tablename__ = "audit_ledger"
    __table_args__ = (
        CheckConstraint("seq >= 1", name="seq_positive"),
        CheckConstraint("length(prev_hash) = 32", name="prev_hash_is_sha256"),
        CheckConstraint("length(entry_hash) = 32", name="entry_hash_is_sha256"),
        CheckConstraint("length(payload_digest) = 32", name="payload_digest_is_sha256"),
        # Chain traversal and verification both walk a session in sequence
        # order; this is the index that makes the trigger's "previous entry"
        # lookup an index scan rather than a partition scan.
        Index("ix_audit_ledger_session_seq", "session_id", "seq"),
        # Security review: "every capability grant in the last 30 days".
        # Partial, because those categories are a small fraction of entries.
        Index(
            "ix_audit_ledger_security_events",
            "recorded_at",
            "event_type",
            postgresql_where=text(
                "event_category IN ('security', 'consent', 'capability')"
            ),
        ),
        # Containment queries over the JSONB detail payload, e.g.
        # detail @> '{"capability": "tap"}'. GIN with jsonb_path_ops is
        # roughly half the size of the default operator class and faster for
        # pure containment, which is the only way this column is queried.
        Index(
            "ix_audit_ledger_detail",
            "detail",
            postgresql_using="gin",
            postgresql_ops={"detail": "jsonb_path_ops"},
        ),
        {
            # Monthly range partitioning. Ignored by SQLite.
            "postgresql_partition_by": "RANGE (recorded_at)",
        },
    )

    # The partition key must participate in the primary key, so the PK is
    # composite. ``id`` alone remains unique in practice (UUIDv4).
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    id: Mapped[str] = mapped_column(
        PortableUUID, primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # No ForeignKey to sessions: a foreign key from a partitioned table would
    # take a lock on the parent for every partition attach, and — more
    # importantly — audit history must survive the deletion of the session it
    # describes. Referential integrity is deliberately traded for durability of
    # the record, which is the correct priority for an audit log.
    session_id: Mapped[str] = mapped_column(PortableUUID, nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(PortableUUID, nullable=True)

    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    event_category: Mapped[str] = mapped_column(audit_category_enum(), nullable=False)

    #: Structured event payload. JSONB so that security queries can use
    #: containment operators against an index instead of parsing text.
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # --- Chain state ------------------------------------------------------
    #: Per-session monotonic sequence number, assigned by the append trigger on
    #: PostgreSQL and by the service on SQLite. ``BigInteger`` because a busy
    #: deployment's long-lived session can exceed a 32-bit count of events.
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)

    #: SHA-256 over the canonically serialised content fields, computed by the
    #: writer. Lets the database verify chain structure without having to
    #: reproduce Python's JSON canonicalisation byte for byte.
    payload_digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)

    prev_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    entry_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
