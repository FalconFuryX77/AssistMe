"""Trusted device database model for the security-focused assistance flow.

A trusted device is a physical client (phone/tablet/browser) that a user has
explicitly paired with their account. Only devices on the user's trusted list
may act as a helper for that user's assistance sessions.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class TrustedDevice(Base):
    """A device that a user has authorized to assist them."""

    __tablename__ = "trusted_devices"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "device_fingerprint", name="uq_owner_device"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    owner_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_fingerprint: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    # The user account that claimed this device during pairing (the helper).
    helper_user_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    friendly_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    device_platform: Mapped[str | None] = mapped_column(
        String(30), nullable=True  # "android", "ios", "web", "unknown"
    )
    # pending -> accepted -> revoked
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
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


class DevicePairing(Base):
    """A one-time pairing code that binds a new device to a user account."""

    __tablename__ = "device_pairings"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    owner_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_fingerprint: Mapped[str] = mapped_column(
        String(128), nullable=False
    )
    friendly_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    device_platform: Mapped[str | None] = mapped_column(String(30), nullable=True)
    pairing_code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # The user who claimed the setup code (the helper), bound at claim time.
    claimed_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # pending -> confirmed -> expired
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
