"""Trusted contact model — the directional half of a mutual trust edge.

Trust in AssistMe is mutual but stored as two directed rows, one per direction.
That is the right representation: the two directions can be in different states
(A has accepted B, B has not yet accepted A), and revocation is one-sided.

The constraints below encode what "mutual" must mean structurally: no self-
trust, no duplicate edge, and a timeline that cannot run backwards.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base
from core.db.dialect import PortableUUID
from core.db.enums import trust_status_enum


class TrustedContact(Base):
    """Directional trusted-contact relationship between two users."""

    __tablename__ = "trusted_contacts"
    __table_args__ = (
        UniqueConstraint("user_id", "contact_user_id", name="uq_user_contact"),
        CheckConstraint("user_id != contact_user_id", name="no_self_contact"),
        CheckConstraint("updated_at >= created_at", name="updated_after_created"),
        # The contact list screen and every authorisation check read accepted
        # edges only. Revoked rows are kept as evidence but never listed.
        Index(
            "ix_trusted_contacts_accepted",
            "user_id",
            "contact_user_id",
            postgresql_where=text("status = 'accepted'"),
        ),
        # The reverse direction, for "who trusts me?" and for checking whether
        # a pending edge already has its mirror.
        Index("ix_trusted_contacts_reverse", "contact_user_id", "status"),
    )

    id: Mapped[str] = mapped_column(
        PortableUUID, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_user_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        trust_status_enum(), default="pending", nullable=False
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
