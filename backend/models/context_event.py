"""Append-only context telemetry stream (Phase 8, and the ML training source).

The problem this fixes
----------------------
``context_snapshots`` is upserted in place: one row per ``(session_id,
user_id)``, overwritten every time the client reports new context. That is a
reasonable representation of *current* state, and it is what the policy engine
reads. But it means the system **destroys its own history**. After a session
ends, exactly one context row survives, describing the last instant.

For a project whose research contribution is adaptive, learned policy, that is
fatal: there is no dataset. A risk classifier needs the sequence of contexts a
session passed through and what was decided at each; a bandit needs the context
present at the moment each action was taken; a sequence recommender needs
ordered transitions. None of it can be reconstructed from a single overwritten
snapshot.

This table is therefore the append-only event stream, and ``context_snapshots``
becomes a derived current-state cache maintained alongside it. Every context
report writes one immutable event here and updates the snapshot there — the
standard event-sourcing split, with the snapshot as the read-optimised
projection.

Physical design
---------------
* **Range-partitioned by month.** The stream is the fastest-growing table in the
  schema (one row per client report, several per minute per active session).
  Partitioning bounds index size and makes retention a ``DROP TABLE``.
* **BRIN on ``recorded_at``.** Rows arrive in time order, so a BRIN index over
  each partition answers window queries at a fraction of a B-tree's size.
* **Append-only trigger.** Training data that can be edited after the fact is
  training data that can be poisoned; immutability is a correctness property of
  the ML pipeline, not only a security one.
* **Denormalised app columns beside an encrypted payload.** ``foreground_app``
  and its category stay as plain columns because they are grouped and indexed
  by ``mv_app_risk_profile``; the free-form remainder goes in an encrypted JSONB
  blob. The split is exactly the confidentiality/queryability trade-off
  discussed in ``docs/CRYPTOGRAPHY_DESIGN.md``.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.crypto.types import EncryptedJSON
from core.database import Base
from core.db.dialect import JSONB, PortableUUID
from core.db.enums import device_platform_enum, network_type_enum, participant_role_enum


class ContextEvent(Base):
    """One immutable observation of a participant's device context."""

    __tablename__ = "context_events"
    __table_args__ = (
        CheckConstraint(
            "battery_percent IS NULL OR (battery_percent >= 0 AND battery_percent <= 100)",
            name="battery_is_percentage",
        ),
        CheckConstraint(
            "screen_width IS NULL OR screen_width > 0", name="screen_width_positive"
        ),
        CheckConstraint(
            "screen_height IS NULL OR screen_height > 0", name="screen_height_positive"
        ),
        CheckConstraint(
            "screen_density IS NULL OR screen_density > 0",
            name="screen_density_positive",
        ),
        # A device cannot dispatch gestures without accessibility enabled;
        # a client claiming otherwise is misreporting and must not reach a
        # policy decision.
        CheckConstraint(
            "accessibility_gesture_capable = false OR accessibility_enabled = true",
            name="gesture_requires_accessibility",
        ),
        # Training extracts scan one session's events in order.
        Index("ix_context_events_session_time", "session_id", "recorded_at"),
        # mv_app_risk_profile aggregates by app; this supports its refresh and
        # the ad-hoc "what happens in banking apps" research queries.
        Index(
            "ix_context_events_app",
            "foreground_app",
            "foreground_app_category",
            postgresql_where=text("foreground_app IS NOT NULL"),
        ),
        # The high-risk population is small and disproportionately queried.
        Index(
            "ix_context_events_protected",
            "recorded_at",
            postgresql_where=text("is_flag_secure_active OR is_sensitive_app"),
        ),
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

    # As with the audit ledger, no foreign keys: the training corpus must
    # outlive the sessions and accounts it was derived from, and a partitioned
    # table's foreign keys are costly to maintain across partition attachment.
    session_id: Mapped[str] = mapped_column(PortableUUID, nullable=False)
    user_id: Mapped[str] = mapped_column(PortableUUID, nullable=False)

    # --- Platform ---------------------------------------------------------
    platform: Mapped[str] = mapped_column(
        device_platform_enum(), default="unknown", nullable=False
    )
    os_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    device_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    screen_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    screen_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    screen_density: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Foreground application ------------------------------------------
    # Kept in plaintext deliberately: these two columns are the grouping keys
    # of the app risk profile view and the strongest single predictor in the
    # risk model. Encrypting them would make the feature store unbuildable.
    # The privacy cost is bounded by the view's k>=5 aggregation floor.
    foreground_app: Mapped[str | None] = mapped_column(String(200), nullable=True)
    foreground_app_category: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    is_sensitive_app: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # --- Permissions and capability state ---------------------------------
    accessibility_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    accessibility_gesture_capable: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    screen_share_permission: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    microphone_permission: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    remote_control_permission: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # --- Protection state -------------------------------------------------
    is_screen_sharing: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    is_flag_secure_active: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # --- Session state ----------------------------------------------------
    is_in_audio_call: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    role: Mapped[str] = mapped_column(
        participant_role_enum(), default="helpee", nullable=False
    )

    # --- Device conditions ------------------------------------------------
    battery_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_charging: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    network_type: Mapped[str | None] = mapped_column(network_type_enum(), nullable=True)

    #: Client-supplied extras that have no dedicated column. Encrypted, because
    #: an open payload from a personal device is personal data by default.
    extra: Mapped[dict | None] = mapped_column(
        EncryptedJSON("context_events.extra"), nullable=True
    )

    #: Non-personal provenance: schema version, client build, report reason.
    #: Plain JSONB so operational queries can filter on it without keys.
    provenance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
