"""Password and recovery-secret hashing with Argon2id, plus keyed peppering.

Why Argon2id
------------
The inherited implementation used bcrypt at cost 12. bcrypt is not broken, but
it has two properties that matter for this application:

* **72-byte silent truncation.** bcrypt ignores input past 72 bytes. A long
  passphrase is silently weakened, and — worse — two distinct secrets sharing a
  72-byte prefix verify as equal. This is a real correctness bug, not a
  theoretical one.
* **Low memory hardness.** bcrypt's 4 KiB working set is cheap to parallelise on
  GPUs. Argon2id, the Password Hashing Competition winner and the algorithm
  recommended by OWASP and RFC 9106, is memory-hard: raising ``memory_cost``
  raises attacker cost superlinearly while costing the server a fixed amount of
  RAM per verification.

Argon2**id** specifically is the hybrid variant: data-independent addressing in
the first pass (side-channel resistant) then data-dependent addressing (GPU/TMTO
resistant). RFC 9106 names it the default choice when the use case is unknown.

Peppering
---------
Hashes are additionally *peppered*: before hashing, the secret is HMAC'd with a
key held outside the database (the blind-index key ring). An attacker who steals
only the database — the overwhelmingly common breach shape — cannot mount an
offline dictionary attack at all, because they lack the pepper. An attacker who
steals both is left facing Argon2id at full cost. Because the pepper is applied
via HMAC-SHA256 before Argon2, the 72-byte truncation class of bug cannot recur:
the hash input is always exactly 32 bytes.

Migration
---------
:func:`verify_secret` transparently accepts legacy bcrypt hashes and reports
whether the caller should re-hash, so existing credentials keep working and
upgrade opportunistically on next successful use. No forced reset is needed.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from hashlib import sha256

import bcrypt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from core.crypto.keyring import KeyPurpose, KeyRing, get_keyring

__all__ = [
    "PEPPER_DOMAIN_PASSWORD",
    "PEPPER_DOMAIN_RECOVERY",
    "VerificationResult",
    "hash_secret",
    "needs_rehash",
    "verify_secret",
]

PEPPER_DOMAIN_PASSWORD = "auth.password"
PEPPER_DOMAIN_RECOVERY = "auth.recovery_code"

# RFC 9106 §4 "second recommended option" (64 MiB, t=3, p=4), which balances
# ~50-80 ms per verification on commodity server hardware against meaningful
# GPU resistance. Raising memory_cost is the correct lever if hardware allows.
_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # KiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of a secret verification.

    Attributes:
        ok: Whether the secret matched.
        needs_rehash: True when the stored hash uses a legacy scheme or
            out-of-date parameters and should be replaced with a fresh hash of
            the (now known-correct) plaintext.
        scheme: ``"argon2id"`` or ``"bcrypt"``.
    """

    ok: bool
    needs_rehash: bool
    scheme: str


def _pepper(secret: str, domain: str, keyring: KeyRing | None = None) -> bytes:
    """Return HMAC-SHA256(BIK_active, domain || 0x00 || secret).

    The blind-index key ring is reused rather than introducing a third key
    purpose: both uses require a keyed PRF whose key never touches the database,
    and fewer key types means fewer ways to misconfigure a deployment. The
    domain separator guarantees a password hash and a blind index of the same
    string are unrelated values.
    """
    ring = keyring or get_keyring()
    _, key = ring.active(KeyPurpose.BIK)
    message = domain.encode("utf-8") + b"\x00" + secret.encode("utf-8")
    return hmac.new(key, message, sha256).digest()


def hash_secret(
    secret: str,
    *,
    domain: str = PEPPER_DOMAIN_PASSWORD,
    keyring: KeyRing | None = None,
) -> str:
    """Hash a secret with Argon2id over a peppered input.

    Returns:
        A PHC-format string (``$argon2id$v=19$m=...``) safe to store.
    """
    if not isinstance(secret, str):
        raise TypeError("secret must be a string")
    return _HASHER.hash(_pepper(secret, domain, keyring))


def verify_secret(
    secret: str,
    stored_hash: str,
    *,
    domain: str = PEPPER_DOMAIN_PASSWORD,
    keyring: KeyRing | None = None,
) -> VerificationResult:
    """Verify a secret against a stored Argon2id *or* legacy bcrypt hash.

    Never raises on a wrong secret — a mismatch is an expected outcome, not an
    exception — so call sites cannot accidentally leak timing or control flow
    differences between "wrong password" and "malformed hash".
    """
    if not isinstance(secret, str) or not isinstance(stored_hash, str):
        return VerificationResult(ok=False, needs_rehash=False, scheme="unknown")

    if stored_hash.startswith("$argon2"):
        try:
            _HASHER.verify(stored_hash, _pepper(secret, domain, keyring))
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return VerificationResult(ok=False, needs_rehash=False, scheme="argon2id")
        return VerificationResult(
            ok=True,
            needs_rehash=_HASHER.check_needs_rehash(stored_hash),
            scheme="argon2id",
        )

    if stored_hash.startswith("$2"):
        # Legacy bcrypt hashes were computed over the raw secret, unpeppered.
        try:
            ok = bcrypt.checkpw(
                secret.encode("utf-8")[:72], stored_hash.encode("utf-8")
            )
        except ValueError:
            return VerificationResult(ok=False, needs_rehash=False, scheme="bcrypt")
        return VerificationResult(ok=ok, needs_rehash=ok, scheme="bcrypt")

    if len(stored_hash) == 64 and all(c in "0123456789abcdefABCDEF" for c in stored_hash):
        # Legacy unsalted SHA-256 hash used by previous prototype for device secrets/recovery codes
        candidate = sha256(secret.encode("utf-8")).hexdigest()
        ok = hmac.compare_digest(candidate.lower(), stored_hash.lower())
        return VerificationResult(ok=ok, needs_rehash=ok, scheme="sha256")

    return VerificationResult(ok=False, needs_rehash=False, scheme="unknown")



def needs_rehash(stored_hash: str) -> bool:
    """True when a stored hash should be upgraded on next successful verify."""
    if stored_hash.startswith("$argon2"):
        try:
            return _HASHER.check_needs_rehash(stored_hash)
        except InvalidHashError:
            return True
    return True
