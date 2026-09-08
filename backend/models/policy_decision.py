"""Adaptive Policy Engine decision records (Phase 9, research core).

First normal form
-----------------
The inherited table stored the granted capability set as a JSON *string* inside
a ``Text`` column, and the risk reasons as a ``", "``-joined string. Both
violate 1NF, and both caused concrete defects:

* The service reconstructed reasons with ``risk_reasons.split(", ")``. Any
  reason containing a comma — for instance ``"sensitive app in foreground:
  com.bank.app, protected content"`` — was silently split into two bogus
  reasons. A repeating group encoded in a delimited string always eventually
  meets a value containing the delimiter.
* "Which sessions granted ``tap``?" required ``LIKE '%tap%'`` over every row,
  which cannot use an index and matches the substring in other words.
* Nothing constrained the contents. ``negotiated_capabilities`` could hold
  ``'["taps"]'`` and every ``== 'tap'`` check would quietly fail closed or open
  depending on the call site.

Capabilities are now a proper relation, ``policy_decision_capabilities``, with a
foreign key, an enum domain, and a composite primary key that makes duplicates
impossible. Membership tests become indexed joins.

Risk reasons remain a JSONB array rather than a child table, and that asymmetry
is deliberate: reasons are an ordered list of human-readable explanations
attached to one decision, never joined to and never constrained to a fixed
domain. Modelling them as entities would add a table and a join to gain nothing.
JSONB preserves order, preserves commas, and supports containment queries
against a GIN index if they are ever needed. The rule applied here is that a
repeating group becomes a relation when its elements are *referenced*, and a
document when they are merely *carried*.
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
    PrimaryKeyConstraint,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base
from core.db.dialect import JSONB, PortableUUID
from core.db.enums import assistance_mode_enum, capability_enum, risk_level_enum


class PolicyDecision(Base):
    """Latest adaptive policy decision for a session."""

    __tablename__ = "policy_decisions"
    __table_args__ = (
        CheckConstraint("updated_at >= created_at", name="updated_after_created"),
        CheckConstraint(
            "(consent_verified = false) = (consent_granted_at IS NULL)",
            name="consent_flag_matches_timestamp",
        ),
        # The engine's central safety invariant, enforced by the database:
        # elevated interaction modes are unreachable at high risk, whatever the
        # model outputs and whatever a future caller does. A model regression
        # cannot grant tap control inside a banking app, because the row will
        # not commit.
        CheckConstraint(
            "risk_level <> 'high' OR assistance_mode IN ('restricted', 'voice')",
            name="high_risk_limits_mode",
        ),
        CheckConstraint(
            "risk_level <> 'medium' OR assistance_mode <> 'tap'",
            name="medium_risk_forbids_tap",
        ),
        # Model confidence is a probability.
        CheckConstraint(
            "model_confidence IS NULL"
            " OR (model_confidence >= 0 AND model_confidence <= 1)",
            name="confidence_is_probability",
        ),
        CheckConstraint(
            "risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 1)",
            name="risk_score_is_probability",
        ),
        Index("ix_policy_decisions_risk_mode", "risk_level", "assistance_mode"),
    )

    id: Mapped[str] = mapped_column(
        PortableUUID, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        unique=True,
    )
    evaluated_by_user_id: Mapped[str] = mapped_column(
        PortableUUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # --- Risk classification ---------------------------------------------
    risk_level: Mapped[str] = mapped_column(
        risk_level_enum(), default="low", nullable=False
    )

    #: Ordered, human-readable justifications. JSONB array — see module docstring.
    risk_reasons: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    #: Calibrated P(elevated risk) from the model, when a model was used.
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Assistance selection --------------------------------------------
    assistance_mode: Mapped[str] = mapped_column(
        assistance_mode_enum(), default="voice", nullable=False
    )

    # --- Model provenance -------------------------------------------------
    #: Which decision path produced this row. ``rules`` means the model was
    #: unavailable or abstained and the deterministic fallback applied; every
    #: decision must be attributable to a specific artefact for the evaluation
    #: to be reproducible.
    decision_source: Mapped[str] = mapped_column(
        String(20), default="rules", nullable=False
    )
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: True when the rule-based safety envelope reduced the model's proposal.
    #: Counting these is how the evaluation reports the intervention rate.
    envelope_clamped: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # --- Consent verification --------------------------------------------
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
    capabilities = relationship(
        "PolicyDecisionCapability",
        back_populates="decision",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # -- Convenience -------------------------------------------------------

    @property
    def capability_set(self) -> set[str]:
        """Granted capabilities as a plain set."""
        return {row.capability for row in self.capabilities}

    def set_capabilities(self, capabilities: set[str]) -> None:
        """Replace the granted capability set.

        Rewriting the whole collection keeps the relation and the in-memory
        object consistent without callers having to diff it themselves.
        """
        self.capabilities = [
            PolicyDecisionCapability(capability=name) for name in sorted(capabilities)
        ]


class PolicyDecisionCapability(Base):
    """One capability granted by a policy decision (1NF relation)."""

    __tablename__ = "policy_decision_capabilities"
    __table_args__ = (
        # Composite primary key: a decision cannot grant the same capability
        # twice, and no surrogate key is needed for a pure association.
        PrimaryKeyConstraint("decision_id", "capability", name="pk_policy_capability"),
        # "Which sessions ever granted tap control?" — now an index scan.
        Index("ix_policy_capability_lookup", "capability", "decision_id"),
    )

    decision_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("policy_decisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    capability: Mapped[str] = mapped_column(capability_enum(), nullable=False)

    decision = relationship("PolicyDecision", back_populates="capabilities")
