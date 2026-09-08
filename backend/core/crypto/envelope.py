"""AES-256-GCM envelope encryption for individual database fields.

Wire format
-----------
Every ciphertext is a self-describing binary blob, so a value encrypted under an
older key version stays readable without any out-of-band metadata::

    offset  size  field
    ------  ----  -----------------------------------------------------------
    0       1     format version           (currently 0x01)
    1       1     algorithm identifier     (0x01 = AES-256-GCM envelope)
    2       2     KEK version, big-endian uint16
    4       12    DEK wrap nonce
    16      48    wrapped DEK (32 B ciphertext + 16 B GCM tag)
    64      12    payload nonce
    76      ..    payload ciphertext + 16 B GCM tag

Fixed overhead is 92 bytes per encrypted field.

Associated data
---------------
Both GCM operations bind *associated data* that is authenticated but not
encrypted. The payload's associated data includes a caller-supplied context
string, which in practice is ``"<table>.<column>"``. This defeats **ciphertext
relocation**: an attacker with UPDATE privileges cannot lift the ciphertext of
``users.display_name`` into ``chat_messages.body`` and have it decrypt, because
the context in the AAD would no longer match and GCM authentication fails.

Callers that know a stable row identity at write time can bind it too (see
``row_binding``), which additionally defeats *row-swap* attacks within a single
column. The ORM type decorators cannot do this — a type decorator has no access
to the row being flushed — so the default protection is column-level, and
row-level binding is available for call sites that manage it explicitly. This
limitation is deliberate and documented rather than hidden.

Nonces
------
Every nonce is 96 random bits from ``os.urandom``. Because a fresh DEK is
generated for every single field write, the nonce-reuse risk that normally
constrains AES-GCM (2^32 messages per key) does not arise: each DEK encrypts
exactly one message.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.crypto.keyring import KeyPurpose, KeyRing, get_keyring

__all__ = [
    "DecryptionError",
    "EncryptedBlob",
    "decrypt",
    "encrypt",
    "inspect",
]

FORMAT_VERSION = 0x01
ALGORITHM_AES256_GCM_ENVELOPE = 0x01

_NONCE_LEN = 12
_TAG_LEN = 16
_DEK_LEN = 32
_WRAPPED_DEK_LEN = _DEK_LEN + _TAG_LEN  # 48

_HEADER = struct.Struct(">BBH")  # format version, algorithm, kek version
_HEADER_LEN = _HEADER.size  # 4

_DEK_NONCE_OFFSET = _HEADER_LEN
_WRAPPED_DEK_OFFSET = _DEK_NONCE_OFFSET + _NONCE_LEN
_PAYLOAD_NONCE_OFFSET = _WRAPPED_DEK_OFFSET + _WRAPPED_DEK_LEN
_PAYLOAD_OFFSET = _PAYLOAD_NONCE_OFFSET + _NONCE_LEN

OVERHEAD_BYTES = _PAYLOAD_OFFSET + _TAG_LEN  # 92

_DEK_AAD_PREFIX = b"assistme/dek/v1|"
_PAYLOAD_AAD_PREFIX = b"assistme/field/v1|"


class DecryptionError(Exception):
    """Raised when a ciphertext cannot be authenticated or parsed.

    This is intentionally *not* a subclass of ``ValueError``: a failure here
    means either key material is wrong, the row was tampered with, or the
    ciphertext was moved between columns. None of those should be swallowed by
    a generic ``except ValueError``.
    """


@dataclass(frozen=True)
class EncryptedBlob:
    """Parsed, non-sensitive header metadata for an encrypted field."""

    format_version: int
    algorithm: int
    kek_version: int
    payload_bytes: int

    @property
    def plaintext_bytes(self) -> int:
        """Length of the underlying plaintext (GCM is length-preserving)."""
        return self.payload_bytes - _TAG_LEN


def _aad(prefix: bytes, context: str, row_binding: str | None) -> bytes:
    """Build associated data, binding a context and optional row identity."""
    parts = [prefix, context.encode("utf-8")]
    if row_binding:
        parts.append(b"|row=")
        parts.append(row_binding.encode("utf-8"))
    return b"".join(parts)


def encrypt(
    plaintext: bytes,
    *,
    context: str,
    row_binding: str | None = None,
    keyring: KeyRing | None = None,
) -> bytes:
    """Encrypt ``plaintext`` under a fresh DEK wrapped by the active KEK.

    Args:
        plaintext: Raw bytes to protect.
        context: Domain separator, conventionally ``"<table>.<column>"``. It is
            authenticated, so decryption with a different context fails.
        row_binding: Optional additional identity (e.g. a primary key) bound
            into the associated data.
        keyring: Key source. Defaults to the process keyring.

    Returns:
        The self-describing ciphertext blob.
    """
    if not isinstance(plaintext, (bytes, bytearray)):
        raise TypeError("plaintext must be bytes")
    if not context:
        raise ValueError("context is required and must be non-empty")

    ring = keyring or get_keyring()
    kek_version, kek = ring.active(KeyPurpose.KEK)

    dek = os.urandom(_DEK_LEN)
    dek_nonce = os.urandom(_NONCE_LEN)
    payload_nonce = os.urandom(_NONCE_LEN)

    wrapped_dek = AESGCM(kek).encrypt(
        dek_nonce, dek, _aad(_DEK_AAD_PREFIX, context, row_binding)
    )
    payload = AESGCM(dek).encrypt(
        payload_nonce, bytes(plaintext), _aad(_PAYLOAD_AAD_PREFIX, context, row_binding)
    )

    header = _HEADER.pack(
        FORMAT_VERSION, ALGORITHM_AES256_GCM_ENVELOPE, kek_version
    )
    return header + dek_nonce + wrapped_dek + payload_nonce + payload


def decrypt(
    blob: bytes,
    *,
    context: str,
    row_binding: str | None = None,
    keyring: KeyRing | None = None,
) -> bytes:
    """Decrypt a blob produced by :func:`encrypt`.

    Raises:
        DecryptionError: On a malformed blob, unknown key version, or failed
            authentication (tampering, wrong context, or wrong key).
    """
    if not isinstance(blob, (bytes, bytearray)):
        raise DecryptionError("ciphertext must be bytes")
    blob = bytes(blob)

    if len(blob) < OVERHEAD_BYTES:
        raise DecryptionError(
            f"ciphertext is {len(blob)} bytes, shorter than the "
            f"{OVERHEAD_BYTES}-byte minimum envelope"
        )

    format_version, algorithm, kek_version = _HEADER.unpack_from(blob, 0)
    if format_version != FORMAT_VERSION:
        raise DecryptionError(f"unsupported envelope format version {format_version}")
    if algorithm != ALGORITHM_AES256_GCM_ENVELOPE:
        raise DecryptionError(f"unsupported algorithm identifier {algorithm}")

    ring = keyring or get_keyring()
    try:
        kek = ring.get(KeyPurpose.KEK, kek_version)
    except Exception as exc:
        raise DecryptionError(str(exc)) from exc

    dek_nonce = blob[_DEK_NONCE_OFFSET:_WRAPPED_DEK_OFFSET]
    wrapped_dek = blob[_WRAPPED_DEK_OFFSET:_PAYLOAD_NONCE_OFFSET]
    payload_nonce = blob[_PAYLOAD_NONCE_OFFSET:_PAYLOAD_OFFSET]
    payload = blob[_PAYLOAD_OFFSET:]

    try:
        dek = AESGCM(kek).decrypt(
            dek_nonce, wrapped_dek, _aad(_DEK_AAD_PREFIX, context, row_binding)
        )
    except InvalidTag as exc:
        raise DecryptionError(
            "DEK unwrap failed: wrong KEK version, tampered header, or the "
            f"ciphertext does not belong to context {context!r}"
        ) from exc

    try:
        return AESGCM(dek).decrypt(
            payload_nonce, payload, _aad(_PAYLOAD_AAD_PREFIX, context, row_binding)
        )
    except InvalidTag as exc:
        raise DecryptionError(
            f"payload authentication failed for context {context!r}: the stored "
            "value was modified, truncated, or relocated from another column"
        ) from exc


def inspect(blob: bytes) -> EncryptedBlob:
    """Parse header metadata without needing key material.

    Used by the rotation tool to find rows still encrypted under an old KEK,
    and by tests. Never returns plaintext or key bytes.
    """
    blob = bytes(blob)
    if len(blob) < OVERHEAD_BYTES:
        raise DecryptionError("blob too short to inspect")
    format_version, algorithm, kek_version = _HEADER.unpack_from(blob, 0)
    return EncryptedBlob(
        format_version=format_version,
        algorithm=algorithm,
        kek_version=kek_version,
        payload_bytes=len(blob) - _PAYLOAD_OFFSET,
    )
