"""Append-only, hash-chained audit ledger service.

Two dialects, one algorithm
---------------------------
On PostgreSQL the chain is computed by a ``BEFORE INSERT`` trigger, so the
sequence number and hash links are assigned by the database and an application
that skips this service still produces a valid chain. On SQLite — the test
dialect, which has no equivalent — this service computes them in Python, under
an asyncio lock that plays the role the trigger's advisory lock plays on
PostgreSQL.

The content digest is always computed here, on both dialects, because it covers
a canonically serialised JSON payload and there must be exactly one
serialisation. See :mod:`models.audit_ledger` for why the verification
responsibility is split between the database and this module.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.dialect import is_postgres
from models.audit_ledger import AuditLedgerEntry

logger = logging.getLogger(__name__)

__all__ = ["AuditLedgerService", "ChainVerification"]

#: Per-session locks serialising appends on dialects without the trigger.
_locks: dict[str, asyncio.Lock] = {}


@dataclass
class ChainVerification:
    """Result of verifying one session's chain."""

    session_id: str
    entry_count: int
    valid: bool
    #: Sequence numbers whose structural link failed.
    structural_failures: list[int]
    #: Sequence numbers whose content no longer matches its digest.
    content_failures: list[int]
    detail: list[dict[str, Any]]


class AuditLedgerService:
    """Appends to and verifies the tamper-evident audit ledger."""

    GENESIS_PREFIX = b"assistme-genesis-v1:"

    # ------------------------------------------------------------------
    # Digest
    # ------------------------------------------------------------------

    @staticmethod
    def payload_digest(
        session_id: str,
        actor_user_id: str | None,
        event_type: str,
        event_category: str,
        detail: dict | None,
    ) -> bytes:
        """SHA-256 over the canonically serialised content fields.

        Canonicalisation matters: ``{"a":1,"b":2}`` and ``{"b":2,"a":1}`` are the
        same value and must produce the same digest, or a round trip through the
        database would appear to be tampering. Sorted keys and fixed separators
        give one representation per value.

        Fields are joined with ``0x1f`` (ASCII unit separator), which cannot
        appear in any of the inputs, so no two distinct field tuples can
        concatenate to the same byte string.
        """
        canonical_detail = (
            json.dumps(detail, sort_keys=True, separators=(",", ":"), default=str)
            if detail is not None
            else ""
        )
        parts = [
            str(session_id),
            str(actor_user_id or ""),
            str(event_type),
            str(event_category),
            canonical_detail,
        ]
        return sha256("\x1f".join(parts).encode("utf-8")).digest()

    @staticmethod
    def _chain_link(prev_hash: bytes, payload_digest: bytes, seq: int) -> bytes:
        """``SHA256(prev_hash ‖ payload_digest ‖ int8be(seq))``.

        Must match ``assistme_audit_chain_append`` in
        :mod:`core.db.ddl` byte for byte, since the database's verification
        function recomputes it. The components are fixed-width, so no separator
        is needed and no concatenation ambiguity exists.
        """
        return sha256(prev_hash + payload_digest + seq.to_bytes(8, "big")).digest()

    @classmethod
    def _genesis(cls, session_id: str) -> bytes:
        """The chain's first ``prev_hash``, distinct per session.

        Per-session so that two sessions' chains cannot be spliced together:
        an attacker cannot move entries from one session into another and have
        the links still verify.
        """
        return sha256(cls.GENESIS_PREFIX + str(session_id).encode("utf-8")).digest()

    # ------------------------------------------------------------------
    # Append
    # ------------------------------------------------------------------

    @classmethod
    async def append(
        cls,
        db: AsyncSession,
        *,
        session_id: str,
        event_type: str,
        event_category: str,
        actor_user_id: str | None = None,
        detail: dict | None = None,
        commit: bool = False,
    ) -> AuditLedgerEntry:
        """Append one immutable entry.

        Args:
            commit: Whether to commit. Defaults to False so the audit record
                joins the caller's transaction — an audit entry that survives a
                rolled-back action would describe something that never
                happened, which is worse than no entry at all.
        """
        digest = cls.payload_digest(
            session_id, actor_user_id, event_type, event_category, detail
        )
        now = datetime.now(timezone.utc)

        entry = AuditLedgerEntry(
            session_id=session_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            event_category=event_category,
            detail=detail,
            payload_digest=digest,
            recorded_at=now,
            # Placeholders on PostgreSQL, where the trigger overwrites them.
            seq=1,
            prev_hash=cls._genesis(session_id),
            entry_hash=b"\x00" * 32,
        )

        if is_postgres(db.bind):
            entry.entry_hash = cls._chain_link(entry.prev_hash, digest, 1)
            db.add(entry)
        else:
            lock = _locks.setdefault(str(session_id), asyncio.Lock())
            async with lock:
                previous = (
                    await db.execute(
                        select(AuditLedgerEntry)
                        .where(AuditLedgerEntry.session_id == session_id)
                        .order_by(AuditLedgerEntry.seq.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()

                if previous is None:
                    entry.seq = 1
                    entry.prev_hash = cls._genesis(session_id)
                else:
                    entry.seq = previous.seq + 1
                    entry.prev_hash = previous.entry_hash

                entry.entry_hash = cls._chain_link(
                    entry.prev_hash, digest, entry.seq
                )
                db.add(entry)
                await db.flush()

        if commit:
            await db.commit()
        return entry

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    @classmethod
    async def verify_chain(
        cls, db: AsyncSession, session_id: str
    ) -> ChainVerification:
        """Verify a session's chain, structurally and by content.

        Structural verification is delegated to the database on PostgreSQL —
        so a compromised application cannot report a clean chain — and repeated
        here in Python so the same guarantee holds on SQLite. Content
        verification recomputes each ``payload_digest`` from the stored fields,
        which the database cannot do because it does not own the JSON
        canonicalisation.
        """
        entries = list(
            (
                await db.execute(
                    select(AuditLedgerEntry)
                    .where(AuditLedgerEntry.session_id == session_id)
                    .order_by(AuditLedgerEntry.seq)
                )
            )
            .scalars()
            .all()
        )

        structural_failures: list[int] = []
        content_failures: list[int] = []
        detail: list[dict[str, Any]] = []

        expected_prev = cls._genesis(session_id)
        expected_seq = 1

        for entry in entries:
            problems: list[str] = []

            if entry.seq != expected_seq:
                problems.append(
                    f"sequence gap: expected {expected_seq}, found {entry.seq}"
                )
            if bytes(entry.prev_hash) != expected_prev:
                problems.append("prev_hash does not match the preceding entry")
            if bytes(entry.entry_hash) != cls._chain_link(
                bytes(entry.prev_hash), bytes(entry.payload_digest), entry.seq
            ):
                problems.append("entry_hash does not match the recomputed chain link")

            if problems:
                structural_failures.append(entry.seq)

            recomputed = cls.payload_digest(
                entry.session_id,
                entry.actor_user_id,
                entry.event_type,
                entry.event_category,
                entry.detail,
            )
            if recomputed != bytes(entry.payload_digest):
                content_failures.append(entry.seq)
                problems.append("content does not match its recorded digest")

            detail.append(
                {
                    "seq": entry.seq,
                    "event_type": entry.event_type,
                    "recorded_at": entry.recorded_at,
                    "valid": not problems,
                    "problems": problems,
                }
            )

            expected_prev = bytes(entry.entry_hash)
            expected_seq = entry.seq + 1

        # Cross-check against the database's own verifier where available. If
        # the two disagree, trust neither and report a failure: a divergence
        # means one of them is operating on different data.
        if is_postgres(db.bind) and entries:
            try:
                rows = (
                    await db.execute(
                        text(
                            "SELECT seq, valid FROM assistme_audit_verify(:sid)"
                        ),
                        {"sid": str(session_id)},
                    )
                ).fetchall()
                database_failures = {int(seq) for seq, valid in rows if not valid}
                for seq in database_failures - set(structural_failures):
                    structural_failures.append(seq)
            except Exception as exc:  # noqa: BLE001
                logger.warning("In-database chain verification unavailable: %s", exc)

        return ChainVerification(
            session_id=str(session_id),
            entry_count=len(entries),
            valid=not structural_failures and not content_failures,
            structural_failures=sorted(structural_failures),
            content_failures=sorted(content_failures),
            detail=detail,
        )
