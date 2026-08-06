"""Assistance session database model."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class Session(Base):
    """An assistance session between a helper and one or more helpees.

    Lifecycle:  waiting → active → ended
        - waiting:  created by the helper, awaiting the helpee to join
        - active:   at least one participant has joined
        - ended:    session closed (explicitly or by timeout)
    """

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    creator_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="waiting", nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    session_code: Mapped[str] = mapped_column(
        String(8), unique=True, nullable=False, index=True
    )
    timeout_minutes: Mapped[int] = mapped_column(
        Integer, default=30, nullable=False
    )
    remote_control_granted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    remote_control_granted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    remote_control_platform: Mapped[str | None] = mapped_column(
        String(30), nullable=True  # "android_accessibility" or "ios_assistivetouch"
    )
    e2ee_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    e2ee_key_exchange_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    e2ee_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    e2ee_mitm_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
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
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    participants = relationship(
        "SessionParticipant", back_populates="session", cascade="all, delete-orphan"
    )
