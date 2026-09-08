"""SQLAlchemy column types that encrypt transparently at the ORM boundary.

Using these types means application and service code never sees ciphertext:
``user.display_name`` is a plain ``str`` in Python and an authenticated
AES-256-GCM blob in the database. Encryption happens in
``process_bind_param`` (on the way to the driver) and decryption in
``process_result_value`` (on the way back), so every code path that touches the
column — ORM flush, Core insert, bulk update — is covered by construction.

Column context
--------------
Each type is constructed with a ``context`` string that is authenticated as
associated data. Convention is ``"<table>.<column>"``. Getting this wrong is
caught at decrypt time (loudly), not silently.

Failure policy
--------------
``strict=True`` (the default) re-raises :class:`DecryptionError`. A row that
cannot be authenticated is a security event, not a display glitch, so the
request fails rather than rendering a placeholder. Analytics-only columns may
opt into ``strict=False``, which substitutes ``None`` and is appropriate where
one unreadable telemetry row must not take down a dashboard.

Storage
-------
Ciphertext is stored as ``LargeBinary`` — ``BYTEA`` on PostgreSQL, ``BLOB`` on
SQLite — which avoids the 33% inflation of base64 text and keeps the test
dialect working unmodified.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import LargeBinary, String
from sqlalchemy.types import TypeDecorator

from core.crypto.blind_index import DEFAULT_BITS, blind_index
from core.crypto.envelope import DecryptionError, decrypt, encrypt

__all__ = [
    "BlindIndexToken",
    "EncryptedJSON",
    "EncryptedString",
    "EncryptedText",
]


class _EncryptedBase(TypeDecorator):
    """Shared machinery for envelope-encrypted columns."""

    impl = LargeBinary

    #: Safe to participate in SQLAlchemy's compiled-statement cache.
    #:
    #: The cache key covers *SQL compilation*, not bound values: this type
    #: always compiles to the same ``BYTEA``/``BLOB`` placeholder, and
    #: ``process_bind_param`` runs per execution, after the cache lookup. So
    #: randomised ciphertext is generated fresh on every write even with
    #: caching on. Leaving this False costs a full statement recompilation on
    #: every query touching an encrypted column, which on the hot session path
    #: is a measurable regression for no security benefit.
    #:
    #: The cache key incorporates the constructor arguments below, both of
    #: which are immutable scalars.
    cache_ok = True

    def __init__(self, context: str, *, strict: bool = True, **kwargs: Any) -> None:
        if not context or "." not in context:
            raise ValueError(
                "context must be '<table>.<column>' so ciphertext is bound to "
                f"its column; got {context!r}"
            )
        self.context = context
        self.strict = strict
        super().__init__(**kwargs)

    # -- subclass hooks -------------------------------------------------

    def _to_bytes(self, value: Any) -> bytes:  # pragma: no cover - abstract
        raise NotImplementedError

    def _from_bytes(self, raw: bytes) -> Any:  # pragma: no cover - abstract
        raise NotImplementedError

    # -- TypeDecorator --------------------------------------------------

    def process_bind_param(self, value: Any, dialect: Any) -> bytes | None:
        if value is None:
            return None
        return encrypt(self._to_bytes(value), context=self.context)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        raw = bytes(value) if isinstance(value, (bytes, bytearray, memoryview)) else str(value).encode("utf-8")
        try:
            return self._from_bytes(decrypt(raw, context=self.context))
        except DecryptionError:
            try:
                # Transparent fallback for unmigrated legacy plaintext values
                return self._from_bytes(raw)
            except Exception:
                if self.strict:
                    raise
                return None



class EncryptedString(_EncryptedBase):
    """A UTF-8 string stored as an authenticated ciphertext blob."""

    def _to_bytes(self, value: Any) -> bytes:
        if not isinstance(value, str):
            raise TypeError(
                f"{self.context} expects str, got {type(value).__name__}"
            )
        return value.encode("utf-8")

    def _from_bytes(self, raw: bytes) -> str:
        return raw.decode("utf-8")


#: Semantic alias — identical behaviour, signals "long free text" at the model.
EncryptedText = EncryptedString


class EncryptedJSON(_EncryptedBase):
    """A JSON-serialisable structure stored as an authenticated ciphertext blob.

    Used for context telemetry payloads, where the schema is deliberately
    open-ended but the contents are personal data. Note the trade-off against a
    native ``JSONB`` column: encrypted payloads cannot be queried or indexed
    server-side. Fields that must remain queryable are promoted to their own
    non-sensitive columns — see ``docs/CRYPTOGRAPHY_DESIGN.md``.
    """

    def _to_bytes(self, value: Any) -> bytes:
        return json.dumps(
            value, separators=(",", ":"), sort_keys=True, default=str
        ).encode("utf-8")

    def _from_bytes(self, raw: bytes) -> Any:
        return json.loads(raw.decode("utf-8"))


class BlindIndexToken(TypeDecorator):
    """A deterministic search token derived from a plaintext value.

    Assign and query with plaintext; the type derives the token on the way in::

        user.display_name_bi = "Grandma"
        select(User).where(User.display_name_bi == "grandma")   # matches

    Both directions go through ``process_bind_param``, so lookups and writes
    can never disagree about normalisation. Reads return the raw token — the
    plaintext is not recoverable from it, which is the point.
    """

    impl = String(72)  # "v<n>:" + 64 hex chars, with headroom for versions
    cache_ok = True

    def __init__(self, domain: str, *, bits: int = DEFAULT_BITS, normalise: bool = True) -> None:
        if not domain or "." not in domain:
            raise ValueError(
                f"domain must be '<table>.<column>'; got {domain!r}"
            )
        self.domain = domain
        self.bits = bits
        self.normalise = normalise
        super().__init__()

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError(
                f"{self.domain} blind index expects str, got {type(value).__name__}"
            )
        return blind_index(
            value, domain=self.domain, bits=self.bits, normalise=self.normalise
        )

    def process_result_value(self, value: Any, dialect: Any) -> str | None:
        return value
