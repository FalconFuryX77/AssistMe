"""Key rotation: re-encrypting stored data under a new key version.

Rotation is the property that makes key compromise *survivable*. Without it, a
leaked KEK means every historical row is permanently readable by whoever holds
it. With it, an operator provisions a new key version, runs this module, and
retires the old key.

Two rotations, two costs
------------------------
**KEK rotation** is cheap and online-safe. Only the wrapped DEK inside each blob
needs rewriting, and because the envelope is self-describing, old and new rows
coexist during the run. Reads keep working throughout.

**BIK rotation** is expensive and must be planned. A blind index is a one-way
function of plaintext, so a new token can only be derived by decrypting the
source column first. This module therefore rotates blind indexes through the
ORM (which decrypts on load) rather than in SQL.

Batching and restartability
---------------------------
Rows are processed in bounded batches with a commit per batch, so a rotation
over a large table neither holds a long transaction open nor blocks writers for
its full duration. Because the header records the key version of every blob, an
interrupted run is safely resumable: re-running simply skips rows already at the
target version. Progress is reported per batch so an operator can watch a
multi-hour rotation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from sqlalchemy import literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from core.crypto.envelope import DecryptionError, decrypt, encrypt, inspect
from core.crypto.keyring import KeyPurpose, KeyRing, get_keyring

logger = logging.getLogger(__name__)

__all__ = ["RotationReport", "rotate_blind_indexes", "rotate_table_kek"]


@dataclass
class RotationReport:
    """Outcome of a rotation run over one table."""

    table: str
    scanned: int = 0
    rewritten: int = 0
    already_current: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)

    def merge(self, other: "RotationReport") -> None:
        self.scanned += other.scanned
        self.rewritten += other.rewritten
        self.already_current += other.already_current
        self.failed += other.failed
        self.failures.extend(other.failures)

    def summary(self) -> str:
        return (
            f"{self.table}: scanned={self.scanned} rewritten={self.rewritten} "
            f"already_current={self.already_current} failed={self.failed}"
        )


async def rotate_table_kek(
    db: AsyncSession,
    model: Any,
    columns: Sequence[str],
    *,
    batch_size: int = 500,
    keyring: KeyRing | None = None,
    dry_run: bool = False,
) -> RotationReport:
    """Re-wrap every encrypted column of ``model`` under the active KEK.

    The ORM decrypts on load and encrypts on flush, so simply reassigning a
    column to its own value is sufficient to rewrite it under the active key.
    Rows already at the target version are skipped by inspecting the raw blob
    header, which avoids a pointless decrypt/encrypt cycle on a resumed run.

    Args:
        db: Session to work in.
        model: The ORM class to rotate.
        columns: Names of encrypted attributes on that model.
        batch_size: Rows per transaction.
        keyring: Key source. Defaults to the process keyring.
        dry_run: Count what would change without writing.

    Returns:
        A :class:`RotationReport`.
    """
    ring = keyring or get_keyring()
    target_version = ring.active_version(KeyPurpose.KEK)
    report = RotationReport(table=model.__tablename__)

    table = model.__table__
    pk = list(table.primary_key.columns)[0]
    last_seen: Any = None

    while True:
        stmt = select(model).order_by(pk).limit(batch_size)
        if last_seen is not None:
            stmt = stmt.where(pk > last_seen)

        rows = list((await db.execute(stmt)).scalars().all())
        if not rows:
            break

        identifiers = [getattr(row, pk.name) for row in rows]

        # Read the *ciphertext* for this batch in one query, bypassing the ORM
        # type decorators. Without it there is no way to tell which rows are
        # already at the target key version, because the ORM hands back
        # plaintext and never exposes the blob it decrypted.
        raw_by_id = await _raw_ciphertext(db, table, pk, columns, identifiers)

        for row in rows:
            report.scanned += 1
            identifier = getattr(row, pk.name)
            last_seen = identifier
            changed = False

            for column in columns:
                if getattr(row, column, None) is None:
                    continue

                raw = raw_by_id.get(identifier, {}).get(column)
                try:
                    # An unreadable header means the row cannot be shown to be
                    # current, so it is rewritten. Rewriting a row that did not
                    # need it costs one AES-GCM pass; skipping one that did
                    # leaves data under a key the operator is about to retire.
                    if raw is not None and inspect(raw).kek_version == target_version:
                        continue
                    # flag_modified, not a reassignment. Setting an attribute
                    # to the value it already holds is a no-op for SQLAlchemy's
                    # change detection, so no UPDATE is emitted and the row
                    # silently stays under the old key — which is exactly what
                    # an earlier version of this code did while reporting
                    # success. Marking the attribute dirty explicitly forces the
                    # flush, and the type decorator re-encrypts under the
                    # active key on the way out.
                    flag_modified(row, column)
                    changed = True
                except (DecryptionError, ValueError) as exc:
                    report.failed += 1
                    report.failures.append(
                        f"{table.name}.{column} id={identifier}: {exc}"
                    )

            if changed:
                report.rewritten += 1
            else:
                report.already_current += 1

        if dry_run:
            db.expunge_all()
        else:
            await db.commit()

        logger.info("KEK rotation progress — %s", report.summary())

        if len(rows) < batch_size:
            break

    return report


async def rotate_blind_indexes(
    db: AsyncSession,
    model: Any,
    pairs: Sequence[tuple[str, str]],
    *,
    batch_size: int = 500,
    dry_run: bool = False,
) -> RotationReport:
    """Recompute blind-index tokens from their encrypted source columns.

    Args:
        db: Session to work in.
        model: The ORM class to rotate.
        pairs: ``(source_column, index_column)`` tuples, where the source is an
            encrypted plaintext-bearing attribute and the index is a
            :class:`~core.crypto.types.BlindIndexToken` attribute.
        batch_size: Rows per transaction.
        dry_run: Count what would change without writing.

    Note:
        A ``UNIQUE`` constraint on an index column can only be re-satisfied
        atomically. Run this inside a maintenance window, or drop the
        constraint and rebuild it after the run, because a partially rotated
        column briefly holds tokens from two key generations that cannot
        collide-check against each other.
    """
    report = RotationReport(table=model.__tablename__)
    pk = list(model.__table__.primary_key.columns)[0]
    last_seen: Any = None

    while True:
        stmt = select(model).order_by(pk).limit(batch_size)
        if last_seen is not None:
            stmt = stmt.where(pk > last_seen)

        rows = list((await db.execute(stmt)).scalars().all())
        if not rows:
            break

        for row in rows:
            report.scanned += 1
            last_seen = getattr(row, pk.name)
            changed = False

            for source_column, index_column in pairs:
                plaintext = getattr(row, source_column, None)
                if plaintext is None:
                    continue
                try:
                    # Assigning plaintext re-derives the token under the
                    # active BIK inside BlindIndexToken.process_bind_param.
                    # flag_modified covers the case where the derived token is
                    # unchanged (same key version) but the write is still
                    # wanted, and is harmless when the value genuinely differs.
                    setattr(row, index_column, plaintext)
                    flag_modified(row, index_column)
                    changed = True
                except Exception as exc:  # noqa: BLE001 - reported, not raised
                    report.failed += 1
                    report.failures.append(
                        f"{model.__tablename__}.{index_column} id={last_seen}: {exc}"
                    )

            if changed:
                report.rewritten += 1
            else:
                report.already_current += 1

        if dry_run:
            db.expunge_all()
        else:
            await db.commit()

        logger.info("Blind index rotation progress — %s", report.summary())

        if len(rows) < batch_size:
            break

    return report


async def _raw_ciphertext(
    db: AsyncSession,
    table: Any,
    pk: Any,
    columns: Sequence[str],
    identifiers: Sequence[Any],
) -> dict[Any, dict[str, bytes]]:
    """Read raw ciphertext for a batch of rows, bypassing the ORM types.

    ``select(Model)`` returns decrypted plaintext, and SQLAlchemy does not keep
    the blob it decrypted, so the only way to inspect an envelope header is to
    read the column through a Core select that does not carry the type
    decorator. ``literal_column`` does exactly that: the value arrives as the
    driver's native ``bytes``.

    An earlier version tried to recover the blob from the instance's committed
    state, which is empty for a freshly loaded row — so it always returned
    ``None``, the caller skipped every column, and rotation silently rewrote
    nothing while reporting success.
    """
    if not identifiers:
        return {}

    selected = [literal_column(f'"{table.name}"."{name}"').label(name) for name in columns]
    stmt = select(pk.label("__pk"), *selected).where(pk.in_(list(identifiers)))

    result: dict[Any, dict[str, bytes]] = {}
    for row in (await db.execute(stmt)).mappings():
        values: dict[str, bytes] = {}
        for name in columns:
            value = row[name]
            if isinstance(value, (bytes, bytearray, memoryview)):
                values[name] = bytes(value)
        result[row["__pk"]] = values
    return result
