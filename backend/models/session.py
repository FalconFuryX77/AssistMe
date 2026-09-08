"""Assistance session model.

This table carries the schema's most safety-critical state: whether remote
control is granted, and under what recording consent. Those flags decide what
the helper's taps are allowed to do on the helpee's physical device, so the
integrity rules are expressed as database constraints rather than as
conventions the fourteen calling services are each trusted to respect.

Constraints added over the inherited definition
-----------------------------------------------
* ``status`` is a native enum, not a free-text ``VARCHAR(20)``.
* A granted capability must carry its grant timestamp and platform, and an
  ungranted one must not — enforced by ``ck_sessions_control_grant_coherent``.
  Previously a row could claim ``remote_control_granted = true`` with a null
  ``granted_at``, leaving no record of when elevated access began.
* Recording state is likewise coherent: no recording without consent, and no
  recording artefacts without a scope.
* Time ordering is enforced: a session cannot end before it started.
* An ended session must have an ``ended_at``, and a live one must not — which
  is what makes ``duration_seconds`` in ``mv_session_analytics`` trustworthy.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.crypto.types import EncryptedString
from core.database import Base
from core.db.dialect import PortableUUID
from core.db.enums import device_platform_enum, session_status_enum


class Session(Base):
    """An assistance session between exactly one helper and one helpee.

    Lifecycle:  waiting → active → ended
        - waiting:  created, awaiting the other party to join
        - active:   at least one participant has joined
        - ended:    closed explicitly or by timeout
    """

    __tablename__ = "sessions"
    __table_args__ = (
        # --- Temporal integrity -------------------------------------------
        CheckConstraint("updated_at >= created_at", name="updated_after_created"),
        CheckConstraint(
            "ended_at IS NULL OR ended_at >= created_at",
            name="ended_after_created",
        ),
        CheckConstraint(
            "(status = 'ended') = (ended_at IS NOT NULL)",
            name="ended_status_matches_timestamp",
        ),
        CheckConstraint(
            "timeout_minutes > 0 AND timeout_minutes <= 1440",
            name="timeout_in_range",
        ),
        # --- Privilege-grant coherence ------------------------------------
        # A grant without its timestamp and platform is unauditable: there
        # would be no record of when elevated control began or what mechanism
        # it used. The database now refuses that state outright.
        CheckConstraint(
            "(remote_control_granted = false"
            "  AND remote_control_granted_at IS NULL"
            "  AND remote_control_platform IS NULL)"
            " OR (remote_control_granted = true"
            "  AND remote_control_granted_at IS NOT NULL"
            "  AND remote_control_platform IS NOT NULL)",
            name="control_grant_coherent",
        ),
        CheckConstraint(
            "remote_control_granted_at IS NULL"
            " OR remote_control_granted_at >= created_at",
            name="control_granted_within_session",
        ),
        # --- Recording coherence ------------------------------------------
        CheckConstraint(
            "is_recording = false OR recording_consent_granted = true",
            name="recording_requires_consent",
        ),
        CheckConstraint(
            "recording_scope IS NULL"
            " OR recording_scope IN ('screen_and_audio', 'screen_only', 'audio_only')",
            name="recording_scope_valid",
        ),
        CheckConstraint(
            "recording_file_size_bytes IS NULL OR recording_file_size_bytes >= 0",
            name="recording_size_non_negative",
        ),
        CheckConstraint(
            "recording_duration_seconds IS NULL OR recording_duration_seconds >= 0",
            name="recording_duration_non_negative",
        ),
        # --- E2EE coherence -----------------------------------------------
        CheckConstraint(
            "e2ee_mitm_verified = false OR e2ee_key_exchange_complete = true",
            name="mitm_verified_requires_exchange",
        ),
        # --- Access paths --------------------------------------------------
        # The hot query is "my live sessions, newest first". A partial index
        # over only non-ended rows stays small forever, because ended sessions
        # — eventually the overwhelming majority — never enter it.
        Index(
            "ix_sessions_creator_live",
            "creator_id",
            "created_at",
            postgresql_where=text("status <> 'ended'"),
        ),
        # Covering index for the session-list endpoint: PostgreSQL can answer
        # it from the index alone (index-only scan), never touching the heap.
        Index(
            "ix_sessions_status_created",
            "status",
            "created_at",
            postgresql_include=["creator_id", "ended_at"],
        ),
        # Sessions granted elevated control are the population every security
        # review starts from, and they are a small minority of rows.
        Index(
            "ix_sessions_elevated",
            "remote_control_granted_at",
            postgresql_where=text("remote_control_granted"),
        ),
        # Session codes are unique among *live* sessions, not for all time.
        #
        # The inherited schema made the column globally UNIQUE. A six-character
        # code over a 36-symbol alphabet gives 36^6 ≈ 2.18e9 values, so by the
        # birthday bound collisions become common after roughly √(2.18e9) ≈
        # 47,000 sessions *ever created*. The generator retries ten times on
        # collision, so as history accumulates every session creation starts
        # doing more lookups, and eventually the retry budget is exhausted and
        # creation fails outright — a failure whose cause is invisible from the
        # error, and which arrives long after launch.
        #
        # A join code is meaningless once its session has ended, so scoping
        # uniqueness to live sessions bounds the collision space by concurrent
        # sessions rather than by lifetime volume, and keeps the index small.
        Index(
            "uq_sessions_live_code",
            "session_code",
            unique=True,
            postgresql_where=text("status <> 'ended'"),
            sqlite_where=text("status <> 'ended'"),
        ),
    )

    id: Mapped[str] = mapped_column(
        PortableUUID,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    creator_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        session_status_enum(), default="waiting", nullable=False, index=True
    )

    # Free text supplied by the helpee ("my WhatsApp won't open") — personal
    # data describing what they are struggling with, so it is encrypted.
    title: Mapped[str | None] = mapped_column(
        EncryptedString("sessions.title"), nullable=True
    )

    #: Short join code the helpee reads aloud. Unique among *live* sessions
    #: only — see the partial unique index in ``__table_args__``.
    session_code: Mapped[str] = mapped_column(String(8), nullable=False)
    timeout_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)

    # --- Elevated control state ------------------------------------------
    remote_control_granted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    remote_control_granted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    remote_control_platform: Mapped[str | None] = mapped_column(
        String(30), nullable=True  # "android_accessibility" | "ios_assistivetouch"
    )

    # --- End-to-end encryption state --------------------------------------
    e2ee_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    e2ee_key_exchange_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    e2ee_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    e2ee_mitm_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # --- Recording state ---------------------------------------------------
    recording_consent_granted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    recording_scope: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_recording: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recording_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recording_file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recording_duration_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True
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
    audit_logs = relationship(
        "AuditLog", back_populates="session", cascade="all, delete-orphan"
    )
    chat_messages = relationship(
        "ChatMessage", back_populates="session", cascade="all, delete-orphan"
    )
    file_transfers = relationship(
        "FileTransfer", back_populates="session", cascade="all, delete-orphan"
    )
    context_snapshots = relationship(
        "ContextSnapshot", back_populates="session", cascade="all, delete-orphan"
    )
    policy_decision = relationship(
        "PolicyDecision",
        back_populates="session",
        uselist=False,
        cascade="all, delete-orphan",
    )
    assistance_suggestions = relationship(
        "AssistanceSuggestion", back_populates="session", cascade="all, delete-orphan"
    )
