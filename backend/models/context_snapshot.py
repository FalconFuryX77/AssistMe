"""Context Engine database model for per-participant device & session context snapshots.

Stores the latest detected context for each participant so the Adaptive Policy
Engine can classify risk and select appropriate assistance modes (Phase 8).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class ContextSnapshot(Base):
    """Latest known device/session context for a session participant.

    Fields are updated in place (upserted per (session_id, user_id)) whenever a
    client reports new context. This keeps a single, authoritative snapshot.
    """

    __tablename__ = "context_snapshots"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_context_session_user"),
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

    # --- Platform ---
    platform: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown"  # "android", "ios", "web", "unknown"
    )
    os_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    device_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    screen_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    screen_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    screen_density: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Foreground app / activity ---
    foreground_app: Mapped[str | None] = mapped_column(
        String(200), nullable=True  # package name / bundle id
    )
    foreground_app_category: Mapped[str | None] = mapped_column(
        String(50), nullable=True  # "system", "banking", "messaging", "health", "social", "productivity", "unknown"
    )
    is_sensitive_app: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- Accessibility / permissions state ---
    accessibility_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    accessibility_gesture_capable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    screen_share_permission: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    microphone_permission: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    remote_control_permission: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- Screen sharing / security state ---
    is_screen_sharing: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_flag_secure_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- Session state ---
    is_in_audio_call: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="helpee", nullable=False)
    session_status: Mapped[str] = mapped_column(String(20), default="waiting", nullable=False)

    # --- Battery / connectivity (for risk & adaptation) ---
    battery_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_charging: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    network_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True  # "wifi", "cellular", "ethernet", "none", "unknown"
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    session = relationship("Session", back_populates="context_snapshots")
