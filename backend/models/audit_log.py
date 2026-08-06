"""Audit log database model for tracking session events and privacy compliance."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class AuditLog(Base):
    """Structured audit trail record for an assistance session.

    Event Types:
        - session_created
        - session_joined
        - screen_share_started / screen_share_stopped
        - remote_control_granted / remote_control_revoked
        - input_dispatched
        - e2ee_verified
        - recording_consent_updated
        - recording_started / recording_stopped
        - session_ended
    """

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    detail: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    session = relationship("Session", back_populates="audit_logs")
