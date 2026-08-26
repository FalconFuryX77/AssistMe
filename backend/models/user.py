"""User database model."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class User(Base):
    """Registered user account."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    # The install is the identity. These fields are retained only for
    # compatibility with existing SQLite databases; they are never shown or
    # collected by the client.
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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

    __table_args__ = (
        # Display name is the human-facing username in the device-first flow.
        # Case-insensitive uniqueness prevents confusing identities such as
        # "Dad" and "dad" while still allowing legacy nullable accounts.
        Index("uq_users_display_name_ci", func.lower(display_name), unique=True),
    )

    # Relationships
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    task_patterns = relationship(
        "AssistanceTaskPattern", back_populates="user", cascade="all, delete-orphan"
    )
    preferred_mode = relationship(
        "PreferredAssistanceMode", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
