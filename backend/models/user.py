"""User account model.

Personal data on this table is protected at the application layer: the display
name and legacy email are stored as AES-256-GCM ciphertext and searched through
keyed blind indexes. See ``docs/CRYPTOGRAPHY_DESIGN.md``.

A note on the uniqueness check
------------------------------
Display names must be unique case-insensitively. The inherited implementation
expressed that as ``WHERE lower(display_name) = lower(:name)``, which has two
problems: it cannot use the B-tree index on ``display_name`` (the index stores
the un-lowered value), so every registration performed a sequential scan of
``users``; and uniqueness was enforced only by that query, so two concurrent
registrations could both pass the check and both insert.

The blind index fixes both at once. ``display_name_bi`` stores
``HMAC(BIK, normalise(name))`` — normalisation includes case folding — under a
``UNIQUE`` constraint. The check becomes an indexed equality lookup, and
uniqueness is enforced by the database under concurrency rather than by a
check-then-act race in Python.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.crypto.types import BlindIndexToken, EncryptedString
from core.database import Base
from core.db.dialect import PortableUUID


class User(Base):
    """Registered user account (invisible to the user in the device-first flow)."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "updated_at >= created_at",
            name="updated_after_created",
        ),
        # Serves the "recently active accounts" query and the ML training
        # extract, both of which filter to active users ordered by recency.
        # Partial: deactivated rows are never scanned by either, so excluding
        # them keeps the index proportional to the live population rather than
        # to everyone who ever registered.
        Index(
            "ix_users_active_created",
            "created_at",
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[str] = mapped_column(
        PortableUUID,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # -- Personal data (encrypted at rest, searched via blind index) --------
    # The device-first flow synthesises an internal address; the column is
    # retained for compatibility with databases created before that change.
    email: Mapped[str] = mapped_column(
        EncryptedString("users.email"), nullable=False
    )
    email_bi: Mapped[str] = mapped_column(
        BlindIndexToken("users.email"), unique=True, nullable=False, index=True
    )

    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    display_name: Mapped[str | None] = mapped_column(
        EncryptedString("users.display_name"), nullable=True
    )
    display_name_bi: Mapped[str | None] = mapped_column(
        BlindIndexToken("users.display_name"), unique=True, nullable=True, index=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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

    # Relationships
    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    task_patterns = relationship(
        "AssistanceTaskPattern", back_populates="user", cascade="all, delete-orphan"
    )
    preferred_mode = relationship(
        "PreferredAssistanceMode",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    # -- Convenience: keep plaintext and blind index in lockstep ------------

    def set_email(self, value: str) -> None:
        """Assign the email and its blind index together.

        Setting one without the other is the obvious way to corrupt a
        searchable-encrypted column, so both writes live in one method.
        """
        self.email = value
        self.email_bi = value

    def set_display_name(self, value: str | None) -> None:
        """Assign the display name and its blind index together."""
        self.display_name = value
        self.display_name_bi = value
