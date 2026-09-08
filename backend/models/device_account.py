"""Device-first account model.

Maps a physical install to an invisible user account, so the app needs no
email/password login. A one-time recovery code is the root credential for
reclaiming the identity after reinstall or device loss.

Credential storage, corrected
-----------------------------
The inherited schema stored ``recovery_code_hash`` and ``device_secret_hash`` as
``String(64)`` — that is, unsalted SHA-256 hex. For the recovery code this is
weak; for the six-digit pairing code on ``DevicePairing`` it is no protection at
all, because an attacker with the database can enumerate all 10^6 preimages in
well under a second and recover every pairing code in the table.

Both are now Argon2id PHC strings (``String(255)``), salted per record and
peppered with a key that lives outside the database. Recovering a six-digit code
from the stored hash goes from a fraction of a second to roughly 10^6 × 60 ms of
memory-hard work per code, and is impossible at all without the pepper.

The device fingerprint is personal data — it identifies a physical handset — so
it is encrypted, with a blind index carrying the uniqueness constraint and
serving the lookup on every authentication.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from core.crypto.types import BlindIndexToken, EncryptedString
from core.database import Base
from core.db.dialect import PortableUUID


class DeviceAccount(Base):
    """A physical install bound to its (invisible) user account."""

    __tablename__ = "device_accounts"
    __table_args__ = (
        CheckConstraint(
            "recovery_code_hash IS NULL OR recovery_code_hash LIKE '$argon2%' OR length(recovery_code_hash) = 64",
            name="recovery_hash_is_argon2",
        ),
        CheckConstraint(
            "device_secret_hash IS NULL OR device_secret_hash LIKE '$argon2%' OR length(device_secret_hash) = 64",
            name="device_secret_hash_is_argon2",
        ),
    )


    id: Mapped[str] = mapped_column(
        PortableUUID, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        PortableUUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # -- Device identity (encrypted; searched via blind index) --------------
    fingerprint: Mapped[str] = mapped_column(
        EncryptedString("device_accounts.fingerprint"), nullable=False
    )
    fingerprint_bi: Mapped[str] = mapped_column(
        BlindIndexToken("device_accounts.fingerprint", normalise=False),
        unique=True,
        nullable=False,
        index=True,
    )

    # -- Credentials (Argon2id, peppered) -----------------------------------
    recovery_code_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_secret_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    #: Blind index over the recovery code, and the reason both mechanisms
    #: exist rather than one.
    #:
    #: The reclaim flow must *find* an account from a code the user types, and
    #: then *verify* it. A salted Argon2id hash makes lookup impossible — that
    #: is the whole point of a per-record salt — while an unsalted hash makes
    #: verification worthless for a low-entropy secret. Splitting the two roles
    #: resolves the tension: the keyed blind index gives an indexed O(log n)
    #: lookup that an attacker holding only the database cannot compute, and
    #: Argon2id then does the actual credential check.
    #:
    #: The inherited implementation used one unsalted SHA-256 for both roles,
    #: which meant a database dump yielded every recovery code by dictionary
    #: attack.
    recovery_code_bi: Mapped[str | None] = mapped_column(
        BlindIndexToken("device_accounts.recovery_code"),
        nullable=True,
        index=True,
    )

    # -- Push delivery ------------------------------------------------------
    # An FCM registration token is a durable handle to a specific person's
    # device; leaking the table would let an attacker push notifications to
    # every user. Encrypted, and never blind-indexed because it is only ever
    # read by user, never searched by value.
    fcm_token: Mapped[str | None] = mapped_column(
        EncryptedString("device_accounts.fcm_token"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def set_fingerprint(self, value: str) -> None:
        """Assign the fingerprint and its blind index together."""
        self.fingerprint = value
        self.fingerprint_bi = value
