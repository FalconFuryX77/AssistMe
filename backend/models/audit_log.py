"""Legacy audit log.

Superseded by :class:`models.audit_ledger.AuditLedgerEntry`, which is
append-only and hash-chained. This table is retained so that databases created
before the ledger existed still load, and so the migration has somewhere to read
history from; new writes go to the ledger via
:class:`api.services.audit_ledger_service.AuditLedgerService`, which mirrors
into this table only while the deprecation window is open.

Do not add columns here. Add them to the ledger.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base
from core.db.dialect import PortableUUID


class AuditLog(Base):
    """Structured audit trail record for an assistance session (deprecated)."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_session_time", "session_id", "timestamp"),
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
    user_id: Mapped[str | None] = mapped_column(
        PortableUUID,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    session = relationship("Session", back_populates="audit_logs")
