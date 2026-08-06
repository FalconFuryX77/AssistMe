"""File transfer database model."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class FileTransfer(Base):
    """Chunked file transfer record within an assistance session.

    Status:
        - initiating:   file metadata registered, awaiting chunk uploads
        - transferring: chunks currently being uploaded
        - completed:    all chunks uploaded and SHA-256 checksum verified
        - failed:       transfer aborted or checksum mismatch
    """

    __tablename__ = "file_transfers"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    file_size_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    mime_type: Mapped[str] = mapped_column(
        String(100), default="application/octet-stream", nullable=False
    )
    checksum_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default="initiating", nullable=False, index=True
    )
    total_chunks: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    received_chunks: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    download_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    session = relationship("Session", back_populates="file_transfers")
    sender = relationship("User")
