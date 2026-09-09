"""Session Guide models for post-call visual memory and step-by-step recall."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base
from core.db.dialect import PortableUUID


class SessionGuide(Base):
    """A personalized, step-by-step visual how-to guide generated from a session.
    
    Stores the synthesized knowledge and context of what was taught/fixed,
    allowing helpees to review and learn at their own pace without calling back.
    """

    __tablename__ = "session_guides"
    __table_args__ = (
        CheckConstraint("steps_count >= 0", name="ck_session_guides_steps_count_non_negative"),
        Index("ix_session_guides_user_id", "user_id"),
        Index("ix_session_guides_session_id", "session_id"),
    )

    id: Mapped[str] = mapped_column(
        PortableUUID,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    session_id: Mapped[str | None] = mapped_column(
        PortableUUID,
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    helper_id: Mapped[str | None] = mapped_column(
        PortableUUID,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    steps_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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
    steps: Mapped[list["GuideStep"]] = relationship(
        "GuideStep",
        back_populates="guide",
        cascade="all, delete-orphan",
        order_by="GuideStep.step_number",
        lazy="selectin",
    )


class GuideStep(Base):
    """An individual sequential step in a session how-to guide with an optional screenshot."""

    __tablename__ = "guide_steps"
    __table_args__ = (
        CheckConstraint("step_number >= 1", name="ck_guide_steps_step_number_positive"),
        Index("ix_guide_steps_guide_id_step", "guide_id", "step_number"),
    )

    id: Mapped[str] = mapped_column(
        PortableUUID,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    guide_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("session_guides.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    guide: Mapped["SessionGuide"] = relationship("SessionGuide", back_populates="steps")
