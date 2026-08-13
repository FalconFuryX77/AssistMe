"""Adaptive Policy Engine database model.

Persists the latest policy decision (risk classification, negotiated
capabilities, selected assistance mode, consent verification) per session.
Consumed by the API to enforce context-aware assistance (Phase 9).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class PolicyDecision(Base):
    """Latest adaptive policy decision for a session.

    Assistance modes (output of the policy engine):
        - voice:          audio guidance only
        - pointer:        laser pointer / annotation overlay
        - drawing:        freehand drawing & highlighting
        - tap:            remote tap gestures (no drag/keyboard)
        - restricted:     view-only, no interaction

    Risk levels:
        - low:    normal apps, all capabilities available
        - medium: protected content, some capabilities restricted
        - high:   sensitive app / FLAG_SECURE, view-only (restricted)
    """

    __tablename__ = "policy_decisions"

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
        unique=True,
    )
    evaluated_by_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # --- Risk classification ---
    risk_level: Mapped[str] = mapped_column(
        String(20), default="low", nullable=False  # "low", "medium", "high"
    )
    risk_reasons: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Capability negotiation ---
    negotiated_capabilities: Mapped[str | None] = mapped_column(
        Text, nullable=True  # JSON list of granted capabilities
    )

    # --- Assistance selection ---
    assistance_mode: Mapped[str] = mapped_column(
        String(20), default="voice", nullable=False
        # "voice", "pointer", "drawing", "tap", "restricted"
    )

    # --- Consent verification ---
    consent_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    consent_granted_at: Mapped[datetime | None] = mapped_column(
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

    # Relationships
    session = relationship("Session", back_populates="policy_decision")