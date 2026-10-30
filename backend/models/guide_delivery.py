"""Encrypted guide hand-off between the two participants of a help session.

The helper's phone encrypts a finished guide with a key the two phones agreed
over the call's peer-to-peer data channel, so this table only ever holds
ciphertext the server cannot read. A row lives until the helpee's phone
downloads it (then it is deleted) or until it expires.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base
from core.db.dialect import PortableUUID

GUIDE_DELIVERY_TTL = timedelta(days=7)


class GuideDelivery(Base):
    __tablename__ = "guide_deliveries"
    __table_args__ = (
        Index("ix_guide_deliveries_recipient_id", "recipient_id"),
        Index("ix_guide_deliveries_session_id", "session_id"),
    )

    id: Mapped[str] = mapped_column(
        PortableUUID,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    session_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    sender_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    recipient_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc) + GUIDE_DELIVERY_TTL,
        nullable=False,
    )
