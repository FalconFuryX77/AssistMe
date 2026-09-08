"""Session participant model.

Every quality-of-service column here (bitrate, FPS, RTT, loss) is an input to
the adaptive streaming logic and to the ML feature vector. The inherited
definition left all of them unbounded, so a client could report
``packet_loss_percent = 900`` or ``rtt_ms = -1`` and the value would flow
straight into a model feature and an adaptation decision. Range constraints
below make the database reject physically impossible telemetry at the boundary,
which is where input validation belongs when several services write the column.

The overlap invariant
---------------------
The product's central constraint is that *a helper serves one helpee at a
time*. That is a statement about intervals: a user's participation windows must
not overlap. It cannot be expressed as a ``UNIQUE`` constraint, and checking it
in Python is a check-then-act race — two concurrent accepts both read "no
active session" and both insert.

PostgreSQL expresses it exactly, with an exclusion constraint::

    EXCLUDE USING gist (
        user_id WITH =,
        tstzrange(joined_at, left_at) WITH &&
    ) WHERE (status <> 'left')

An open-ended participation is ``[joined_at, ∞)``, so a second concurrent join
overlaps the first and is rejected by the index at commit time — correct under
any level of concurrency, with no application locking. It lives in the
migration rather than here because SQLite has no equivalent; see
``tests/test_postgres_schema.py`` for the concurrency proof.
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
from core.db.enums import participant_role_enum, participant_status_enum


class SessionParticipant(Base):
    """A user participating in an assistance session."""

    __tablename__ = "session_participants"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_session_user"),
        # --- Temporal integrity -------------------------------------------
        CheckConstraint(
            "left_at IS NULL OR left_at >= joined_at", name="left_after_joined"
        ),
        CheckConstraint(
            "last_seen_at >= joined_at", name="last_seen_after_joined"
        ),
        CheckConstraint(
            "(status = 'left') = (left_at IS NOT NULL)",
            name="left_status_matches_timestamp",
        ),
        # --- Physically meaningful telemetry ------------------------------
        CheckConstraint(
            "packet_loss_percent >= 0 AND packet_loss_percent <= 100",
            name="packet_loss_is_percentage",
        ),
        CheckConstraint("rtt_ms >= 0 AND rtt_ms <= 60000", name="rtt_plausible"),
        CheckConstraint(
            "video_bitrate_kbps > 0 AND video_bitrate_kbps <= 100000",
            name="bitrate_plausible",
        ),
        CheckConstraint("video_fps > 0 AND video_fps <= 120", name="fps_plausible"),
        CheckConstraint(
            "video_resolution IN ('1080p', '720p', '480p', '360p', '240p')",
            name="resolution_known",
        ),
        CheckConstraint(
            "audio_quality IN ('high', 'medium', 'low')", name="audio_quality_known"
        ),
        CheckConstraint(
            "audio_route IN ('speaker', 'earpiece', 'bluetooth', 'headset')",
            name="audio_route_known",
        ),
        CheckConstraint(
            "screen_orientation IN ('portrait', 'landscape')",
            name="orientation_known",
        ),
        # A participant who is not sharing cannot have a sharing platform, and
        # FLAG_SECURE is only meaningful while a screen is actually being sent.
        CheckConstraint(
            "is_screen_sharing = true OR screen_share_platform IS NULL",
            name="share_platform_requires_sharing",
        ),
        # --- Access paths --------------------------------------------------
        # "Which session is this user currently in?" runs on every websocket
        # frame. Partial index over live participants only.
        Index(
            "ix_participants_user_live",
            "user_id",
            postgresql_where=text("status = 'connected'"),
        ),
        Index("ix_participants_session_role", "session_id", "role"),
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
    role: Mapped[str] = mapped_column(participant_role_enum(), nullable=False)
    status: Mapped[str] = mapped_column(
        participant_status_enum(), default="connected", nullable=False
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

    # --- Screen sharing ----------------------------------------------------
    is_screen_sharing: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    screen_share_platform: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_flag_secure_active: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    screen_orientation: Mapped[str] = mapped_column(
        String(20), default="portrait", nullable=False
    )

    # --- Audio -------------------------------------------------------------
    is_in_audio_call: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    is_audio_muted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    audio_route: Mapped[str] = mapped_column(
        String(20), default="speaker", nullable=False
    )
    audio_quality: Mapped[str] = mapped_column(
        String(20), default="high", nullable=False
    )

    # --- Video / network quality (adaptive streaming + ML features) --------
    video_resolution: Mapped[str] = mapped_column(
        String(10), default="720p", nullable=False
    )
    video_bitrate_kbps: Mapped[int] = mapped_column(
        Integer, default=1500, nullable=False
    )
    video_fps: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    rtt_ms: Mapped[float] = mapped_column(Float, default=50.0, nullable=False)
    packet_loss_percent: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )
    is_active_speaker: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # Relationships
    session = relationship("Session", back_populates="participants")
