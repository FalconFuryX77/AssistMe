"""Assistance request and privilege-escalation models.

The security-focused assistance flow:

1. The helpee taps "I need help".
2. The request lands on the helper's device as a popup (accept / deny).
3. Acceptance grants **only** overlay drawing by default — least privilege.
4. If the helper needs more, they request escalation.
5. The helpee sees a plain-language risk screen; only explicit acceptance of
   the stated risks escalates capabilities.

The escalation table is the most security-sensitive record in the system: it is
the documentary proof that an elderly person was shown a risk disclosure and
consented before someone else could tap on their phone. Its constraints are
written to make an unprovable grant impossible to store — an approved
escalation *must* carry an accepted disclaimer, a response timestamp, and a
non-empty granted capability set, or it does not commit.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.crypto.types import EncryptedString
from core.database import Base
from core.db.dialect import JSONB, PortableUUID
from core.db.enums import escalation_status_enum, request_status_enum


class AssistanceRequest(Base):
    """A help request from a helpee to a helper."""

    __tablename__ = "assistance_requests"
    __table_args__ = (
        CheckConstraint(
            "responded_at IS NULL OR responded_at >= created_at",
            name="responded_after_created",
        ),
        # A resolved request must record when it was resolved; a pending one
        # must not claim to have been. Without this, "time to answer" — a
        # headline usability metric — is computed over rows that may be lying.
        CheckConstraint(
            "(status = 'pending') = (responded_at IS NULL)",
            name="response_time_matches_status",
        ),
        CheckConstraint(
            "helper_user_id IS NULL OR helper_user_id <> helpee_user_id",
            name="helper_is_not_helpee",
        ),
        # The ring path polls "do I have a pending request?" constantly, and
        # pending rows are a vanishing fraction of history.
        Index(
            "ix_assistance_requests_pending",
            "helper_user_id",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_assistance_requests_helpee_time", "helpee_user_id", "created_at"),
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
    helpee_user_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    helper_user_id: Mapped[str | None] = mapped_column(
        PortableUUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    helper_device_fingerprint: Mapped[str | None] = mapped_column(
        EncryptedString("assistance_requests.helper_device_fingerprint"), nullable=True
    )

    #: The helpee's own words about what is wrong. Among the most sensitive
    #: free text in the system — it describes a vulnerable person's difficulty —
    #: so it is encrypted rather than stored in the clear as before.
    message: Mapped[str | None] = mapped_column(
        EncryptedString("assistance_requests.message"), nullable=True
    )

    status: Mapped[str] = mapped_column(
        request_status_enum(), default="pending", nullable=False
    )

    #: Capabilities granted on acceptance, as a JSONB array. Previously a
    #: ``String(200)`` holding a delimited list.
    initial_capabilities: Mapped[list | None] = mapped_column(JSONB, nullable=True)

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
    __table_args__ = (
        CheckConstraint(
            "responded_at IS NULL OR responded_at >= created_at",
            name="responded_after_created",
        ),
        CheckConstraint(
            "(status = 'pending') = (responded_at IS NULL)",
            name="response_time_matches_status",
        ),
        # The consent invariant. An approved escalation that cannot show an
        # accepted disclaimer and a concrete granted set is not evidence of
        # informed consent, and this schema will not store one.
        CheckConstraint(
            "status <> 'approved'"
            " OR (disclaimer_accepted = true"
            "     AND disclaimer_text IS NOT NULL"
            "     AND granted_capabilities IS NOT NULL)",
            name="approval_requires_accepted_disclaimer",
        ),
        # Conversely, a rejected or pending escalation must not carry grants.
        CheckConstraint(
            "status = 'approved' OR granted_capabilities IS NULL",
            name="grants_only_when_approved",
        ),
        Index(
            "ix_escalations_pending",
            "session_id",
            "created_at",
            postgresql_where=text("status = 'pending'"),
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
    request_id: Mapped[str | None] = mapped_column(
        PortableUUID,
        ForeignKey("assistance_requests.id", ondelete="CASCADE"),
        nullable=True,
    )
    requested_by_user_id: Mapped[str] = mapped_column(
        PortableUUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    target_capabilities: Mapped[list] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        escalation_status_enum(), default="pending", nullable=False
    )

    #: The exact wording shown to the helpee. Retained verbatim: if the
    #: disclosure text changes between releases, an audit must be able to
    #: establish what *this* person actually agreed to.
    disclaimer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    disclaimer_accepted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    granted_capabilities: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
