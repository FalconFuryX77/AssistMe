"""File transfer model for chunked in-session transfers.

The chunk counters here are the transfer's completion state, and the inherited
definition left them free to contradict themselves: ``received_chunks`` could
exceed ``total_chunks``, a transfer could be ``completed`` with chunks
outstanding, and ``file_size_bytes`` could be negative. Each of those states
would be reported to the client as a valid progress figure. The constraints
below make the impossible ones unstorable.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.crypto.types import EncryptedString
from core.database import Base
from core.db.dialect import PortableUUID


class FileTransfer(Base):
    """Chunked file transfer record within an assistance session.

    Status:
        - initiating:   metadata registered, awaiting chunk uploads
        - transferring: chunks currently being uploaded
        - completed:    all chunks uploaded and SHA-256 checksum verified
        - failed:       aborted or checksum mismatch
    """

    __tablename__ = "file_transfers"
    __table_args__ = (
        CheckConstraint(
            "status IN ('initiating', 'transferring', 'completed', 'failed')",
            name="status_known",
        ),
        CheckConstraint("file_size_bytes >= 0", name="size_non_negative"),
        CheckConstraint("total_chunks >= 1", name="total_chunks_positive"),
        CheckConstraint(
            "received_chunks >= 0 AND received_chunks <= total_chunks",
            name="received_within_total",
        ),
        # A completed transfer must actually have received everything and have
        # somewhere to download it from.
        CheckConstraint(
            "status <> 'completed'"
            " OR (received_chunks = total_chunks AND download_url IS NOT NULL)",
            name="completed_means_complete",
        ),
        CheckConstraint("length(checksum_sha256) = 64", name="checksum_is_sha256_hex"),
        # In-flight transfers are the only ones the progress endpoint polls.
        Index(
            "ix_file_transfers_active",
            "session_id",
            "created_at",
            postgresql_where=text("status IN ('initiating', 'transferring')"),
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
    sender_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: A filename can disclose a great deal ("bank-statement-march.pdf",
    #: "prescription.jpg"), so it is treated as personal data.
    filename: Mapped[str] = mapped_column(
        EncryptedString("file_transfers.filename"), nullable=False
    )

    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(
        String(100), default="application/octet-stream", nullable=False
    )
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="initiating", nullable=False, index=True
    )
    total_chunks: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    received_chunks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    download_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    session = relationship("Session", back_populates="file_transfers")
    sender = relationship("User")
