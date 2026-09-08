"""Application-layer cryptography for AssistMe.

Public surface:

* :mod:`core.crypto.keyring` — versioned KEK/BIK material from the runtime.
* :mod:`core.crypto.envelope` — AES-256-GCM envelope encryption of field bytes.
* :mod:`core.crypto.blind_index` — keyed deterministic tokens for equality search.
* :mod:`core.crypto.types` — SQLAlchemy column types that apply both transparently.
* :mod:`core.crypto.hashing` — Argon2id secret hashing with a keyed pepper.
* :mod:`core.crypto.rotation` — offline re-encryption when a key version changes.

See ``docs/CRYPTOGRAPHY_DESIGN.md`` for the threat model and the reasoning
behind each construction, including what the blind index deliberately leaks.
"""

from core.crypto.blind_index import blind_index, normalise_value
from core.crypto.envelope import DecryptionError, decrypt, encrypt
from core.crypto.hashing import hash_secret, verify_secret
from core.crypto.keyring import KeyMaterialError, KeyRing, get_keyring, reset_keyring
from core.crypto.types import (
    BlindIndexToken,
    EncryptedJSON,
    EncryptedString,
    EncryptedText,
)

__all__ = [
    "BlindIndexToken",
    "DecryptionError",
    "EncryptedJSON",
    "EncryptedString",
    "EncryptedText",
    "KeyMaterialError",
    "KeyRing",
    "blind_index",
    "decrypt",
    "encrypt",
    "get_keyring",
    "hash_secret",
    "normalise_value",
    "reset_keyring",
    "verify_secret",
]
