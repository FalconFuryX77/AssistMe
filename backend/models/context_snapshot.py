"""Current-state projection of the context event stream (Phase 8).

Relationship to :mod:`models.context_event`
-------------------------------------------
This table holds exactly one row per ``(session_id, user_id)``: the most recent
context reported by that participant. ``context_events`` holds the immutable
history. Every context report writes both — one append there, one upsert here.

That is the standard event-sourcing split, and the reason for it is that the two
readers want opposite things. The policy engine, on the hot path of a live
session, wants "what is true right now" as a single indexed row lookup. The ML
pipeline wants every observation ever made, in order. Serving both from one
table means either the policy engine pays for an aggregate over history on every
evaluation, or the pipeline has no history at all — which is precisely the
situation the inherited schema was in.

The projection is derivable, so it is safe to rebuild: dropping and recomputing
it from ``context_events`` yields the same state. That property is what makes it
a cache rather than a second source of truth.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base
from core.db.dialect import PortableUUID
from core.db.enums import device_platform_enum, network_type_enum, participant_role_enum


class ContextSnapshot(Base):
    """Latest known device/session context for a session participant."""

    __tablename__ = "context_snapshots"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_context_session_user"),
        CheckConstraint(
            "battery_percent IS NULL OR (battery_percent >= 0 AND battery_percent <= 100)",
            name="battery_is_percentage",
        ),
        CheckConstraint(
            "screen_width IS NULL OR screen_width > 0", name="screen_width_positive"
        ),
        CheckConstraint(
            "screen_height IS NULL OR screen_height > 0", name="screen_height_positive"
        ),
        CheckConstraint(
            "screen_density IS NULL OR screen_density > 0",
            name="screen_density_positive",
        ),
        CheckConstraint(
            "accessibility_gesture_capable = false OR accessibility_enabled = true",
            name="gesture_requires_accessibility",
        ),
        CheckConstraint(
            "session_status IN ('waiting', 'active', 'ended')",
            name="session_status_known",
        ),
        # The policy engine's read: "the helpee's current context in this
        # session". Covered by the unique constraint above; this partial index
        # additionally serves the "which live sessions are in a protected app"
        # security query without scanning ended ones.
        Index(
            "ix_context_snapshots_protected",
            "session_id",
            postgresql_where=text("is_flag_secure_active OR is_sensitive_app"),
        ),
    )

    id: Mapped[str] = mapped_column(
        PortableUUID, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # --- Platform ---
    platform: Mapped[str] = mapped_column(
        device_platform_enum(), nullable=False, default="unknown"
    )
    os_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    device_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    screen_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    screen_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    screen_density: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Foreground app / activity ---
    foreground_app: Mapped[str | None] = mapped_column(String(200), nullable=True)
    foreground_app_category: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    is_sensitive_app: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # --- Accessibility / permissions state ---
    accessibility_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    accessibility_gesture_capable: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    screen_share_permission: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    microphone_permission: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    remote_control_permission: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # --- Screen sharing / security state ---
    is_screen_sharing: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    is_flag_secure_active: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # --- Session state ---
    is_in_audio_call: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    role: Mapped[str] = mapped_column(
        participant_role_enum(), default="helpee", nullable=False
    )
    session_status: Mapped[str] = mapped_column(
        String(20), default="waiting", nullable=False
    )

    # --- Battery / connectivity ---
    battery_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_charging: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    network_type: Mapped[str | None] = mapped_column(network_type_enum(), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    session = relationship("Session", back_populates="context_snapshots")
