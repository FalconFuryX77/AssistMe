"""Intelligent Assistance models (Phase 11).

What was here before
--------------------
``AssistanceTaskPattern`` held a single ``occurrence_count`` per
``(user, app, platform, action)`` signature, and a pattern was "learned" once
that counter reached 2. Confidence was reported as ``count / 4``, capped at 1.

Three things are wrong with that as a learning system, and all three are fixed
by the columns below rather than by a cleverer query:

* **No notion of success.** A count records that an action was *taken*, never
  that it *worked*. An action the helper tried five times because it kept
  failing outranked one that worked first time. Reward is now tracked
  separately from exposure, so the score estimates P(success | context), which
  is the quantity a suggestion should be ranked by.
* **No recency.** A counter is monotonic, so a habit abandoned a year ago
  outranks one formed last week forever. ``decayed_count`` maintains an
  exponentially time-weighted count, so evidence ages out continuously instead
  of never.
* **Confidence that is not a probability.** ``count / 4`` reaches 1.0 after four
  observations and is not calibrated against anything. The score is now a
  Beta-Bernoulli posterior mean with a weak prior, which is a genuine
  probability estimate, is well-defined at zero observations, and is
  conservative exactly when the evidence is thin. That property matters here:
  the cold-start case is an elderly user the system knows nothing about, and
  over-confident suggestions to that user are the failure mode to avoid.

``AssistanceActionTransition`` is new. It maintains the empirical first-order
transition matrix between assistance actions, updated online, which is what the
sequence recommender in :mod:`ml.sequence` consumes and what lets the system
suggest a *next* step rather than only a repeated one.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base
from core.db.dialect import PortableUUID
from core.db.enums import assistance_mode_enum

#: Beta(α₀, β₀) prior for the success-rate posterior. Jeffreys' prior
#: (½, ½) is the standard uninformative choice for a Bernoulli rate: it is
#: invariant under reparameterisation and, unlike Beta(1,1), does not pull a
#: genuinely-always-successful pattern down as hard once evidence accumulates.
PRIOR_ALPHA = 0.5
PRIOR_BETA = 0.5

#: Half-life of behavioural evidence. Six weeks is a compromise between
#: tracking a genuine change in a user's habits and being whipsawed by a single
#: unusual week.
DECAY_HALF_LIFE_DAYS = 42.0


class AssistanceTaskPattern(Base):
    """A learned association between a context signature and an action."""

    __tablename__ = "assistance_task_patterns"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "context_signature", name="uq_task_pattern_user_signature"
        ),
        CheckConstraint("occurrence_count >= 1", name="occurrence_positive"),
        CheckConstraint(
            "success_count >= 0 AND success_count <= occurrence_count",
            name="success_within_occurrences",
        ),
        CheckConstraint("decayed_count >= 0", name="decayed_count_non_negative"),
        CheckConstraint(
            "decayed_success >= 0 AND decayed_success <= decayed_count",
            name="decayed_success_within_count",
        ),
        CheckConstraint(
            "last_occurred_at >= first_occurred_at", name="last_after_first"
        ),
        # Ranking query: a user's patterns, strongest first.
        Index("ix_task_patterns_user_strength", "user_id", "decayed_count"),
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

    #: SHA-256 of the canonical (app, platform, action) tuple.
    context_signature: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    foreground_app: Mapped[str | None] = mapped_column(String(200), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(20), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)

    # --- Raw counts (exposure and reward, kept separate) ------------------
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # --- Time-decayed counts ----------------------------------------------
    #: Exponentially decayed equivalents, recomputed on each update by
    #: multiplying the stored value by ``0.5 ** (Δt / half_life)`` before
    #: incrementing. Storing the decayed value rather than recomputing from an
    #: event history keeps the update O(1) and the read a single column.
    decayed_count: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    decayed_success: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    first_occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        # Derived from first_occurred_at rather than calling now() a second
        # time. Two independent now() defaults are evaluated microseconds
        # apart and can order the "last" timestamp *before* the "first" one on
        # the very first insert — which the last_after_first constraint
        # correctly rejects. Reading the sibling parameter makes them equal by
        # construction.
        default=lambda ctx: ctx.get_current_parameters()["first_occurred_at"],
        nullable=False,
    )

    # Relationships
    user = relationship("User", back_populates="task_patterns")

    @property
    def posterior_success_rate(self) -> float:
        """Beta-Bernoulli posterior mean of P(success), using decayed evidence.

        Well-defined with zero observations (returns the prior mean, 0.5) and
        shrinks toward the prior when evidence is thin, which is exactly the
        conservatism a cold-start user needs.
        """
        alpha = PRIOR_ALPHA + self.decayed_success
        beta = PRIOR_BETA + (self.decayed_count - self.decayed_success)
        return alpha / (alpha + beta)


class AssistanceActionTransition(Base):
    """Empirical first-order transition counts between assistance actions.

    Maintained online so the recommender has a usable model from the first
    session, without waiting for an offline training run. ``NULL``
    ``prev_action`` represents the session-start state, which is what makes the
    chain able to predict a *first* action as well as a subsequent one.
    """

    __tablename__ = "assistance_action_transitions"
    __table_args__ = (
        PrimaryKeyConstraint(
            "user_id", "prev_action", "next_action", name="pk_action_transition"
        ),
        CheckConstraint("transition_count >= 1", name="transition_count_positive"),
        CheckConstraint("decayed_count >= 0", name="decayed_count_non_negative"),
        Index("ix_action_transitions_lookup", "user_id", "prev_action", "decayed_count"),
    )

    user_id: Mapped[str] = mapped_column(
        PortableUUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    #: Empty string denotes the session-start state; a nullable column cannot
    #: participate in a primary key.
    prev_action: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    next_action: Mapped[str] = mapped_column(String(50), nullable=False)

    transition_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    decayed_count: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    last_occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class PreferredAssistanceMode(Base):
    """Per-user preferred assistance mode."""

    __tablename__ = "preferred_assistance_modes"
    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="confidence_is_probability"
        ),
        CheckConstraint("observation_count >= 0", name="observations_non_negative"),
    )

    id: Mapped[str] = mapped_column(
        PortableUUID, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        unique=True,
    )
    mode: Mapped[str] = mapped_column(assistance_mode_enum(), nullable=False)

    #: Whether the preference was stated by the user or inferred from
    #: behaviour. An inferred preference may be overridden by the policy
    #: engine; a stated one is respected up to the safety ceiling.
    source: Mapped[str] = mapped_column(String(20), default="explicit", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    user = relationship("User", back_populates="preferred_mode")


class AssistanceSuggestion(Base):
    """A context-aware suggestion produced by the engine, and its fate."""

    __tablename__ = "assistance_suggestions"
    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="confidence_is_probability"
        ),
        CheckConstraint("rank >= 1", name="rank_positive"),
        CheckConstraint(
            "(accepted IS NULL) = (responded_at IS NULL)",
            name="acceptance_has_timestamp",
        ),
        CheckConstraint(
            "responded_at IS NULL OR responded_at >= created_at",
            name="responded_after_created",
        ),
        # Suggestion quality is evaluated over accepted/rejected outcomes.
        Index("ix_suggestions_outcome", "suggestion_type", "accepted", "created_at"),
        Index("ix_suggestions_session", "session_id", "rank"),
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
    user_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    suggestion_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: The concrete action being suggested, so acceptance can be attributed to
    #: an action rather than only to a headline string.
    action: Mapped[str | None] = mapped_column(String(50), nullable=True)

    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    #: Position in the returned list. Needed to compute rank-aware metrics
    #: (MRR, NDCG) from production logs rather than only offline.
    rank: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    #: Which model produced it, for attribution in the evaluation.
    model_version: Mapped[str | None] = mapped_column(String(96), nullable=True)

    # --- Feedback loop -----------------------------------------------------
    accepted: Mapped[bool | None] = mapped_column(nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    session = relationship("Session", back_populates="assistance_suggestions")
