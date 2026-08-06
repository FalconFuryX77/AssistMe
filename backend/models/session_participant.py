"""Session participant database model."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class SessionParticipant(Base):
    """A user participating in an assistance session.

    Roles:
        - helper:  the user providing assistance (session creator)
        - helpee:  the user receiving assistance

    Status:
        - connected:    currently in the session
        - disconnected: lost connection (eligible for recovery)
        - left:         voluntarily left the session
    """

    __tablename__ = "session_participants"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_session_user"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False  # "helper" or "helpee"
    )
    status: Mapped[str] = mapped_column(
        String(20), default="connected", nullable=False
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    is_screen_sharing: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    screen_share_platform: Mapped[str | None] = mapped_column(
        String(20), nullable=True  # "android" or "ios"
    )
    is_flag_secure_active: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    screen_orientation: Mapped[str] = mapped_column(
        String(20), default="portrait", nullable=False  # "portrait" or "landscape"
    )
    is_in_audio_call: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    is_audio_muted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    audio_route: Mapped[str] = mapped_column(
        String(20), default="speaker", nullable=False  # "speaker", "earpiece", "bluetooth", "headset"
    )
    audio_quality: Mapped[str] = mapped_column(
        String(20), default="high", nullable=False  # "high", "medium", "low"
    )

    # Relationships
    session = relationship("Session", back_populates="participants")
