"""Assistance request & escalation database models.

Captures the security-focused assistance flow:
  1. Helpee taps "request help" on their device.
  2. A request lands on the helper's device as a popup (accept / deny).
  3. Acceptance grants ONLY overlay drawing by default (least privilege).
  4. If the helper needs more control, they request escalation.
  5. The helpee sees a clear risk disclaimer; only explicit acceptance
     (acceptance of the stated risks) escalates capabilities.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class AssistanceRequest(Base):
    """A help request from a helpee to a helper (one per active request)."""

    __tablename__ = "assistance_requests"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    helpee_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    helper_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    helper_device_fingerprint: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    # pending -> accepted -> denied
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )
    initial_capabilities: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class AssistanceEscalation(Base):
    """A helper's request for more control, gated by an explicit risk disclaimer."""

    __tablename__ = "assistance_escalations"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("assistance_requests.id", ondelete="CASCADE"), nullable=True
    )
    requested_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    target_capabilities: Mapped[str] = mapped_column(String(200), nullable=False)
    # pending -> approved -> rejected
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False
    )
    disclaimer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    disclaimer_accepted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    granted_capabilities: Mapped[str | None] = mapped_column(String(200), nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )