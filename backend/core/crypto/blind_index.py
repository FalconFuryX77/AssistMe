"""Deterministic blind indexes for equality search over encrypted columns.

The problem
-----------
Once a column is encrypted with a randomised AEAD (as ``core.crypto.envelope``
is, correctly), two rows holding the same plaintext produce different
ciphertexts. That is exactly what we want for confidentiality, and exactly what
breaks ``WHERE display_name = 'Grandma'`` and any ``UNIQUE`` constraint.

The construction
----------------
A *blind index* is a keyed, deterministic token stored in a companion column::

    token = HMAC-SHA256(BIK_v, domain || 0x00 || normalise(plaintext))

Because it is keyed, an attacker holding only the database cannot compute
tokens for guessed plaintexts — unlike an unkeyed hash, which is trivially
dictionary-attacked over a small domain such as first names. Because it is
deterministic, equality lookups and uniqueness constraints work with a plain
B-tree index.

What it still leaks
-------------------
Determinism necessarily leaks *equality*: an attacker learns which rows share a
value, and can mount frequency analysis against a known plaintext distribution
(e.g. that "Mum" is a common display name). Three mitigations are applied:

* **Per-domain separation.** The ``domain`` string is mixed in, so the same
  plaintext in two different columns yields two unrelated tokens. Cross-column
  correlation attacks fail.
* **Key versioning.** Tokens carry the BIK version that produced them, so the
  index can be rotated (which requires re-deriving from plaintext, hence the
  rotation tool decrypts and rewrites).
* **Optional truncation.** ``bits`` below 256 deliberately induces collisions,
  flattening the frequency distribution at the cost of requiring a decrypt-side
  post-filter. Use it for search convenience columns; use the full 256 bits
  where a ``UNIQUE`` constraint must be exact.

This trade-off is inherent to searchable encryption without an oblivious index
structure; it is stated here rather than papered over.

Normalisation
-------------
Values are NFKC-normalised, case-folded, whitespace-collapsed, and stripped.
This makes lookups behave the way users expect ("Grandma " matches "grandma")
but means the index cannot distinguish values that differ only in those
respects. Columns where case is significant must pass ``normalise=False``.
"""

from __future__ import annotations

import hmac
import unicodedata
from hashlib import sha256

from core.crypto.keyring import KeyPurpose, KeyRing, get_keyring

__all__ = [
    "DEFAULT_BITS",
    "blind_index",
    "normalise_value",
    "parse_token",
]

#: Full-width tokens: collision probability is negligible, so a UNIQUE
#: constraint on the token column is equivalent to one on the plaintext.
DEFAULT_BITS = 256

_SEPARATOR = b"\x00"


def normalise_value(value: str) -> str:
    """Canonicalise a string before hashing.

    NFKC folds visually identical Unicode forms together; case folding is the
    Unicode-correct superset of lowercasing; whitespace is collapsed so that
    accidental double spaces do not create distinct identities.
    """
    text = unicodedata.normalize("NFKC", value)
    text = " ".join(text.split())
    return text.casefold()


def blind_index(
    value: str,
    *,
    domain: str,
    bits: int = DEFAULT_BITS,
    normalise: bool = True,
    keyring: KeyRing | None = None,
    version: int | None = None,
) -> str:
    """Compute a versioned blind-index token for ``value``.

    Args:
        value: Plaintext to tokenise.
        domain: Column-scoped separator, conventionally ``"<table>.<column>"``.
        bits: Token width. Must be a multiple of 8 in ``[64, 256]``.
        normalise: Apply :func:`normalise_value` first.
        keyring: Key source. Defaults to the process keyring.
        version: Force a specific BIK version (used by the rotation tool to
            compute both the old and the new token). Defaults to active.

    Returns:
        ``"v<version>:<hex>"`` — the version prefix lets a rotation run
        distinguish stale tokens with a simple ``LIKE 'v1:%'`` scan.
    """
    if not isinstance(value, str):
        raise TypeError("blind index input must be a string")
    if not domain:
        raise ValueError("domain is required and must be non-empty")
    if bits % 8 or not (64 <= bits <= 256):
        raise ValueError("bits must be a multiple of 8 between 64 and 256")

    ring = keyring or get_keyring()
    if version is None:
        version, key = ring.active(KeyPurpose.BIK)
    else:
        key = ring.get(KeyPurpose.BIK, version)

    text = normalise_value(value) if normalise else value
    message = domain.encode("utf-8") + _SEPARATOR + text.encode("utf-8")
    digest = hmac.new(key, message, sha256).digest()

    return f"v{version}:{digest[: bits // 8].hex()}"


def parse_token(token: str) -> tuple[int, str]:
    """Split ``"v<version>:<hex>"`` into its parts.

    Raises:
        ValueError: If the token is not in the expected form.
    """
    prefix, _, digest = token.partition(":")
    if not prefix.startswith("v") or not prefix[1:].isdigit() or not digest:
        raise ValueError(f"malformed blind index token: {token!r}")
    return int(prefix[1:]), digest
