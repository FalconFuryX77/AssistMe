"""Immutable log of every model-influenced decision, and its outcome.

This table is what makes the research claims checkable. Three things depend on
it and cannot be reconstructed without it:

**Off-policy evaluation.** Estimating how a *new* policy would have performed
from data collected under the *deployed* policy requires knowing, for each
decision, the probability the deployed policy assigned to the action it took —
the propensity. Inverse-propensity and doubly-robust estimators divide by it.
Propensity is only knowable at decision time; it can never be recovered
afterwards. Logging it is the difference between being able to evaluate a
policy change offline and having to A/B test every idea in production on
elderly users' phones.

**Reproducibility.** Each row records the exact model version and the feature
vector fed to it, so any historical decision can be replayed against the
artefact that produced it. "The model behaved oddly last Tuesday" becomes a
query rather than a guess.

**Delayed reward.** The outcome of an assistance decision is not known when the
decision is made — it arrives when the helpee accepts or rejects the escalation,
or when the session ends successfully. The reward columns are therefore filled
in later by ``record_outcome``, which is the single exception to this table's
append-only rule and is scoped to columns that are ``NULL`` at insert.

Append-only, with one exception
-------------------------------
The immutability trigger on this table permits an ``UPDATE`` only when it fills
previously-``NULL`` outcome columns and touches nothing else. That keeps the
feature vector and the propensity — the parts an attacker or a careless
migration could use to fabricate favourable evaluation results — genuinely
immutable, while still allowing the reward to arrive late.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base
from core.db.dialect import JSONB, PortableUUID


class MLDecisionLog(Base):
    """One model-influenced decision, its context, and its eventual reward."""

    __tablename__ = "ml_decision_log"
    __table_args__ = (
        CheckConstraint(
            "propensity IS NULL OR (propensity > 0 AND propensity <= 1)",
            name="propensity_is_probability",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_is_probability",
        ),
        CheckConstraint(
            "reward IS NULL OR (reward >= 0 AND reward <= 1)",
            name="reward_in_unit_interval",
        ),
        CheckConstraint(
            "(reward IS NULL) = (outcome_recorded_at IS NULL)",
            name="reward_has_timestamp",
        ),
        CheckConstraint(
            "outcome_recorded_at IS NULL OR outcome_recorded_at >= recorded_at",
            name="outcome_after_decision",
        ),
        CheckConstraint(
            "decision_kind IN ('risk', 'mode_selection', 'recommendation', 'anomaly')",
            name="decision_kind_known",
        ),
        # Training extracts pull one decision kind and one model version at a
        # time, in time order.
        Index("ix_ml_decision_kind_model", "decision_kind", "model_version", "recorded_at"),
        # Off-policy evaluation needs only the rows that have a reward, which
        # are a minority; a partial index keeps that scan proportional to the
        # labelled set rather than the whole log.
        Index(
            "ix_ml_decision_labelled",
            "decision_kind",
            "recorded_at",
            postgresql_where=text("reward IS NOT NULL"),
        ),
        Index("ix_ml_decision_session", "session_id", "recorded_at"),
        {"postgresql_partition_by": "RANGE (recorded_at)"},
    )

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    id: Mapped[str] = mapped_column(
        PortableUUID, primary_key=True, default=lambda: str(uuid.uuid4())
    )

    session_id: Mapped[str | None] = mapped_column(PortableUUID, nullable=True)
    user_id: Mapped[str | None] = mapped_column(PortableUUID, nullable=True)

    #: Which model family produced this decision.
    decision_kind: Mapped[str] = mapped_column(String(20), nullable=False)

    #: Registry identifier of the exact artefact, e.g.
    #: ``risk_classifier/2026-09-01T10-00-00Z/hgb``.
    model_version: Mapped[str] = mapped_column(String(96), nullable=False)

    #: The feature vector as scored, by name. Stored so a decision can be
    #: replayed exactly; feature engineering changes over time, so recomputing
    #: from raw context would not reproduce the historical input.
    features: Mapped[dict] = mapped_column(JSONB, nullable=False)

    #: The action the policy took (a mode name, a risk level, a ranked action).
    action: Mapped[str] = mapped_column(String(40), nullable=False)

    #: Actions that were admissible under the safety envelope at decision time.
    #: Needed by off-policy estimators: an action absent from the historical
    #: action set has no support and its counterfactual is not identifiable.
    candidate_actions: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    #: P(action | context) under the *deployed* policy. The denominator of
    #: every importance-weighted estimate.
    propensity: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: The model's own confidence in its output, distinct from propensity.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: True when the rule-based envelope overrode the model's proposal.
    envelope_clamped: Mapped[bool | None] = mapped_column(nullable=True)

    #: Realised reward in [0, 1], written later by ``record_outcome``.
    reward: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_label: Mapped[str | None] = mapped_column(String(40), nullable=True)
    outcome_recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Wall-clock inference cost, for the latency budget reported in the
    #: evaluation. A policy that is accurate but slow is not deployable on the
    #: hot path of a live assistance session.
    latency_us: Mapped[int | None] = mapped_column(Integer, nullable=True)
