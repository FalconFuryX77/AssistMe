"""In-app chat message model.

The vision document records a deliberate, disclosed trade-off: chat is
server-readable in v1, because the helper may need to send a link or a code that
the helpee cannot type. That decision is about *end-to-end* encryption — whether
the server can read plaintext in memory — and it does not license storing the
messages of vulnerable users in the clear on disk.

Both columns are therefore encrypted at rest. The server can still read chat
while it holds key material, exactly as the disclosed trade-off says; a stolen
database or backup cannot. This is the distinction between confidentiality
against the operator (not claimed) and confidentiality against theft (claimed,
and now actually delivered).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.crypto.types import EncryptedText
from core.database import Base
from core.db.dialect import PortableUUID


class ChatMessage(Base):
    """A text message sent within an assistance session."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        # A message flagged as end-to-end encrypted must carry the E2EE
        # payload, and a plaintext one must not — otherwise the client cannot
        # tell which field to render and silently shows the wrong thing.
        CheckConstraint(
            "(is_encrypted = false AND encrypted_payload IS NULL)"
            " OR (is_encrypted = true AND encrypted_payload IS NOT NULL)",
            name="e2ee_payload_matches_flag",
        ),
        # Transcript retrieval is always "this session, in time order".
        Index("ix_chat_messages_session_time", "session_id", "timestamp"),
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

    #: Server-readable message body, encrypted at rest.
    content: Mapped[str] = mapped_column(
        EncryptedText("chat_messages.content"), nullable=False
    )

    is_encrypted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    #: Client-side E2EE ciphertext, when the session negotiated it. Encrypted
    #: again at rest: double encryption costs 92 bytes and one AES-GCM pass,
    #: and removes the need to reason about whether the client's scheme is
    #: sound before deciding the server's storage is safe.
    encrypted_payload: Mapped[str | None] = mapped_column(
        EncryptedText("chat_messages.encrypted_payload"), nullable=True
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    session = relationship("Session", back_populates="chat_messages")
    sender = relationship("User")
