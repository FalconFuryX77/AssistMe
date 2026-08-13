"""Intelligent Assistance database models (Phase 11).

- AssistanceTaskPattern: learned repeated task patterns (e.g. "always help with
  settings → remote control"). The engine counts how often a given context
  signature resulted in a specific assistance action, so it can suggest
  automation.
- PreferredAssistanceMode: per-user memory of the assistance mode they prefer.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class AssistanceTaskPattern(Base):
    """A learned repeated task signature and its automated action.

    context_signature is a stable hash of (foreground_app, platform, action).
    When the same signature is observed multiple times, the engine treats it as
    a "repeated task" and can suggest/perform the associated action.
    """

    __tablename__ = "assistance_task_patterns"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "context_signature",
            name="uq_task_pattern_user_signature",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    context_signature: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    foreground_app: Mapped[str | None] = mapped_column(String(200), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(20), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "remote_control", "screen_share", "voice"
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    user = relationship("User", back_populates="task_patterns")


class PreferredAssistanceMode(Base):
    """Per-user preferred assistance mode memory."""

    __tablename__ = "preferred_assistance_modes"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        unique=True,
    )
    mode: Mapped[str] = mapped_column(
        String(20), nullable=False  # "voice", "pointer", "drawing", "tap", "restricted"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    user = relationship("User", back_populates="preferred_mode")


class AssistanceSuggestion(Base):
    """A context-aware assistance suggestion produced by the engine."""

    __tablename__ = "assistance_suggestions"

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
    suggestion_type: Mapped[str] = mapped_column(
        String(50), nullable=False
        # "repeated_task", "context_help", "preferred_mode"
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    session = relationship("Session", back_populates="assistance_suggestions")
