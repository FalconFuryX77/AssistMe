"""Refresh token model.

Bearer tokens are stored hashed, not in plaintext
-------------------------------------------------
The inherited table stored the refresh token itself in a ``UNIQUE`` indexed
column. That makes the database a bearer-credential store: anyone who obtains a
dump — a leaked backup, a compromised replica, an over-broad analytics grant —
can immediately mint access tokens for every user in it, with no cracking step.
Refresh tokens outlive access tokens by design (seven days here), so the
compromise window is wide.

Only the SHA-256 digest is stored now, and lookup hashes the presented token
before querying. A stolen dump yields digests, which are useless as bearer
credentials.

Why SHA-256 and not Argon2id here
---------------------------------
Password hashing is slow *because* passwords have low entropy and must resist
offline guessing. A refresh token is 48 bytes from ``secrets.token_urlsafe`` —
384 bits of uniform randomness. There is no dictionary to guess and no feasible
brute force, so a memory-hard KDF would buy nothing while adding ~60 ms to every
token refresh. A single SHA-256 is the correct construction for high-entropy
secrets, and the same reasoning is why session cookies are conventionally
handled this way. (See :mod:`core.crypto.hashing` for the opposite case: the
six-digit pairing code, which *is* low entropy and does need Argon2id.)
"""

import uuid
from datetime import datetime, timezone
from hashlib import sha256

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base
from core.db.dialect import PortableUUID


class RefreshToken(Base):
    """A long-lived refresh credential, stored as a digest for revocation."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        CheckConstraint("length(token_hash) = 64", name="token_hash_is_sha256_hex"),
        # Every refresh looks up a live token. Revoked and expired rows are
        # retained for forensics but never matched, so they are excluded from
        # the index that the hot path uses.
        Index(
            "ix_refresh_tokens_live",
            "token_hash",
            postgresql_where=text("NOT revoked"),
        ),
        Index("ix_refresh_tokens_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        PortableUUID, primary_key=True, default=lambda: str(uuid.uuid4())
    )

    #: SHA-256 hex digest of the issued token. Never the token itself.
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )

    user_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    user = relationship("User", back_populates="refresh_tokens")

    @staticmethod
    def digest(raw_token: str) -> str:
        """Return the storage digest for a raw refresh token.

        Both issuing and lookup go through this method so the two can never
        disagree about the hashing scheme.
        """
        return sha256(raw_token.encode("utf-8")).hexdigest()
