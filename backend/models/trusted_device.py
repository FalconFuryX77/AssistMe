"""Trusted device and pairing models.

A trusted device is a physical client that a user has explicitly paired with
their account. Only devices on a user's trusted list may act as a helper for
that user's sessions, so the integrity of these two tables is the whole of the
anti-stranger protection the product promises.

Referential integrity, restored
-------------------------------
``TrustedDevice.helper_user_id`` and ``DevicePairing.claimed_by_user_id`` were
declared as ``String(36)`` with ``index=True`` but **no foreign key**. They hold
user identifiers and are compared against ``users.id`` throughout the pairing
service, yet nothing stopped them pointing at a deleted or nonexistent account.
Deleting a user left dangling references that the trust checks then evaluated
against ``None``. Both are now real foreign keys with ``ON DELETE SET NULL``, so
removing an account cleanly detaches its claims instead of leaving them to be
resolved by code that assumed they could not dangle.

Pairing-code storage is the other correction: a six-digit code under unsalted
SHA-256 is recoverable by exhaustive search in milliseconds. See
:mod:`models.device_account` for the reasoning behind the Argon2id replacement.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.crypto.types import BlindIndexToken, EncryptedString
from core.database import Base
from core.db.dialect import PortableUUID
from core.db.enums import device_platform_enum, pairing_status_enum, trust_status_enum


class TrustedDevice(Base):
    """A device that a user has authorised to assist them."""

    __tablename__ = "trusted_devices"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id", "device_fingerprint_bi", name="uq_owner_device"
        ),
        CheckConstraint("updated_at >= created_at", name="updated_after_created"),
        # A device may not be trusted by its own owner's account acting as its
        # own helper; that would let a single compromised install self-approve.
        CheckConstraint(
            "helper_user_id IS NULL OR helper_user_id <> owner_user_id",
            name="helper_is_not_owner",
        ),
        # The hot path — "may this helper act for this owner?" — touches only
        # accepted rows, which are a minority once revocations accumulate.
        Index(
            "ix_trusted_devices_active",
            "owner_user_id",
            "helper_user_id",
            postgresql_where=text("status = 'accepted'"),
        ),
    )

    id: Mapped[str] = mapped_column(
        PortableUUID, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    owner_user_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    device_fingerprint: Mapped[str] = mapped_column(
        EncryptedString("trusted_devices.device_fingerprint"), nullable=False
    )
    device_fingerprint_bi: Mapped[str] = mapped_column(
        BlindIndexToken("trusted_devices.device_fingerprint", normalise=False),
        nullable=False,
        index=True,
    )

    #: The account that claimed this device during pairing (the helper).
    helper_user_id: Mapped[str | None] = mapped_column(
        PortableUUID,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    #: A human label chosen by the user ("Mum's phone") — personal data.
    friendly_name: Mapped[str | None] = mapped_column(
        EncryptedString("trusted_devices.friendly_name"), nullable=True
    )
    device_platform: Mapped[str | None] = mapped_column(
        device_platform_enum(), nullable=True
    )
    status: Mapped[str] = mapped_column(
        trust_status_enum(), default="pending", nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def set_device_fingerprint(self, value: str) -> None:
        """Assign the fingerprint and its blind index together."""
        self.device_fingerprint = value
        self.device_fingerprint_bi = value


class DevicePairing(Base):
    """A one-time pairing code binding a new device to a user account."""

    __tablename__ = "device_pairings"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        CheckConstraint(
            "failed_attempts >= 0 AND failed_attempts <= 100",
            name="failed_attempts_bounded",
        ),
        # Scoped to live pairings: expired rows are retained for audit and may
        # carry a pre-migration hash that cannot be converted (an Argon2id hash
        # needs the plaintext). They are unusable for authentication regardless,
        # because the claim path filters on status.
        CheckConstraint(
            "status NOT IN ('pending', 'awaiting_helper')"
            " OR pairing_code_hash LIKE '$argon2%'",
            name="pairing_hash_is_argon2",
        ),
        CheckConstraint(
            "claimed_by_user_id IS NULL OR claimed_by_user_id <> owner_user_id",
            name="claimer_is_not_owner",
        ),
        # Claiming a code scans live pairings only. Expired and confirmed rows
        # are retained for audit but never searched, so they stay out of the
        # index that the claim path uses.
        Index(
            "ix_device_pairings_open",
            "owner_user_id",
            "expires_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[str] = mapped_column(
        PortableUUID, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    owner_user_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    device_fingerprint: Mapped[str] = mapped_column(
        EncryptedString("device_pairings.device_fingerprint"), nullable=False
    )
    device_fingerprint_bi: Mapped[str] = mapped_column(
        BlindIndexToken("device_pairings.device_fingerprint", normalise=False),
        nullable=False,
        index=True,
    )

    friendly_name: Mapped[str | None] = mapped_column(
        EncryptedString("device_pairings.friendly_name"), nullable=True
    )
    device_platform: Mapped[str | None] = mapped_column(
        device_platform_enum(), nullable=True
    )

    #: Argon2id PHC string over the peppered six-digit code.
    pairing_code_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    #: Blind index over the same code, for lookup.
    #:
    #: The inherited claim path loaded *every* open pairing for an owner and
    #: compared hashes in Python — O(n) work per attempt, and a natural target
    #: for a resource-exhaustion attack once an owner accumulates pairings.
    #: With a keyed index the candidate set is found by index lookup, and
    #: Argon2id verifies only the one or two rows that actually collide on six
    #: digits.
    pairing_code_bi: Mapped[str] = mapped_column(
        BlindIndexToken("device_pairings.pairing_code", normalise=False),
        nullable=False,
        index=True,
    )

    claimed_by_user_id: Mapped[str | None] = mapped_column(
        PortableUUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        pairing_status_enum(), default="pending", nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def set_device_fingerprint(self, value: str) -> None:
        """Assign the fingerprint and its blind index together."""
        self.device_fingerprint = value
        self.device_fingerprint_bi = value
