"""Versioned key material management for application-layer cryptography.

Design
------
AssistMe protects personal data with *application-layer envelope encryption*
rather than relying solely on transparent disk encryption. The threat model is
explicit (see ``docs/CRYPTOGRAPHY_DESIGN.md``):

* A stolen database dump, a leaked backup, or a compromised read-replica must
  not reveal display names, device labels, chat content, or context telemetry.
* Database administrators and analysts with SQL access must not be able to read
  personal fields without also holding key material that lives outside the
  database.
* Key compromise must be *recoverable* — hence versioned keys and an offline
  re-encryption path (``core.crypto.rotation``).

Key hierarchy::

    Key Encryption Key (KEK, versioned)          <- from environment / KMS
        └── Data Encryption Key (DEK, per record) <- random, wrapped by KEK
                └── field ciphertext (AES-256-GCM)

    Blind Index Key (BIK, versioned)             <- from environment / KMS
        └── HMAC-SHA256 deterministic search token

Only the *wrapped* DEK ever reaches storage, so compromising a single row's
ciphertext does not help an attacker decrypt any other row. KEKs and BIKs are
supplied by the runtime; the source tree contains no production key material.

Key provisioning
----------------
Production keys are supplied as environment variables of the form::

    ASSISTME_KEK_V3=<base64url 32 bytes>     # active KEK (highest version wins)
    ASSISTME_KEK_V2=<base64url 32 bytes>     # retained for decrypt-only
    ASSISTME_BIK_V1=<base64url 32 bytes>     # blind index key

or, preferably, as files referenced by ``ASSISTME_KEY_FILE`` (a JSON document
with the same names), which allows mounting a Kubernetes Secret without
exposing key bytes in the process environment listing.

In development, when no key material is provided, keys are derived
deterministically from ``SECRET_KEY`` via HKDF so that a developer database
stays readable across restarts. This derivation is refused outright when
``APP_ENV`` is production.
"""

from __future__ import annotations

import base64
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

__all__ = [
    "KeyMaterialError",
    "KeyPurpose",
    "KeyRing",
    "get_keyring",
    "reset_keyring",
]

#: Length in bytes of every symmetric key handled here (AES-256 / HMAC-SHA256).
KEY_LENGTH = 32

#: Environment variable prefixes, by purpose.
_ENV_PREFIX = {
    "kek": "ASSISTME_KEK_V",
    "bik": "ASSISTME_BIK_V",
}


class KeyMaterialError(RuntimeError):
    """Raised when key material is missing, malformed, or used incorrectly."""


class KeyPurpose:
    """Namespace of supported key purposes (avoids stringly-typed call sites)."""

    KEK = "kek"
    BIK = "bik"

    ALL = (KEK, BIK)


@dataclass(frozen=True)
class VersionedKey:
    """A single key version.

    Attributes:
        purpose: ``"kek"`` or ``"bik"``.
        version: Monotonically increasing integer. Higher is newer.
        material: Raw 32-byte key.
    """

    purpose: str
    version: int
    material: bytes

    def __post_init__(self) -> None:
        if self.purpose not in KeyPurpose.ALL:
            raise KeyMaterialError(f"Unknown key purpose: {self.purpose!r}")
        if len(self.material) != KEY_LENGTH:
            raise KeyMaterialError(
                f"{self.purpose} v{self.version} must be {KEY_LENGTH} bytes, "
                f"got {len(self.material)}"
            )

    def __repr__(self) -> str:  # pragma: no cover - defensive, never log material
        return f"VersionedKey(purpose={self.purpose!r}, version={self.version})"


class KeyRing:
    """Holds every known key version and identifies the active one.

    The keyring is deliberately immutable after construction. Rotation creates a
    *new* keyring rather than mutating a live one, so an in-flight request can
    never observe a half-rotated key set.
    """

    def __init__(self, keys: list[VersionedKey], *, derived: bool = False) -> None:
        if not keys:
            raise KeyMaterialError("A keyring requires at least one key")

        self._by_purpose: dict[str, dict[int, VersionedKey]] = {}
        for key in keys:
            self._by_purpose.setdefault(key.purpose, {})[key.version] = key

        for purpose in KeyPurpose.ALL:
            if purpose not in self._by_purpose:
                raise KeyMaterialError(
                    f"No {purpose.upper()} key material available; refusing to start"
                )

        self._active: dict[str, int] = {
            purpose: max(versions) for purpose, versions in self._by_purpose.items()
        }
        #: True when key material was derived from SECRET_KEY (development only).
        self.derived = derived

    # -- lookup ---------------------------------------------------------

    def active_version(self, purpose: str) -> int:
        """Return the version number new ciphertext should be written with."""
        try:
            return self._active[purpose]
        except KeyError as exc:  # pragma: no cover - guarded in __init__
            raise KeyMaterialError(f"Unknown key purpose: {purpose!r}") from exc

    def get(self, purpose: str, version: int) -> bytes:
        """Return raw key material for a specific version.

        Raises:
            KeyMaterialError: if that version is unknown, which is what happens
                when a database row was encrypted under a key that has since
                been removed from the runtime. Failing loudly is correct: silent
                data loss is worse than a startup error.
        """
        try:
            return self._by_purpose[purpose][version].material
        except KeyError as exc:
            known = sorted(self._by_purpose.get(purpose, {}))
            raise KeyMaterialError(
                f"{purpose.upper()} version {version} is not loaded. "
                f"Loaded versions: {known or 'none'}. Ciphertext written under a "
                f"retired key cannot be read; restore the key or run a rotation."
            ) from exc

    def active(self, purpose: str) -> tuple[int, bytes]:
        """Return ``(version, material)`` for the active key of a purpose."""
        version = self.active_version(purpose)
        return version, self.get(purpose, version)

    def versions(self, purpose: str) -> list[int]:
        """All loaded versions for a purpose, ascending."""
        return sorted(self._by_purpose.get(purpose, {}))

    def describe(self) -> dict[str, object]:
        """Non-sensitive summary suitable for health endpoints and logs."""
        return {
            "derived_from_secret_key": self.derived,
            "kek_versions": self.versions(KeyPurpose.KEK),
            "kek_active": self.active_version(KeyPurpose.KEK),
            "bik_versions": self.versions(KeyPurpose.BIK),
            "bik_active": self.active_version(KeyPurpose.BIK),
        }


# ----------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------


def _decode_key(raw: str, label: str) -> bytes:
    """Decode a base64url (padded or unpadded) or hex key string."""
    text = raw.strip()
    if not text:
        raise KeyMaterialError(f"{label} is empty")

    # Hex is accepted because operators often paste `openssl rand -hex 32`.
    if len(text) == KEY_LENGTH * 2 and all(c in "0123456789abcdefABCDEF" for c in text):
        return bytes.fromhex(text)

    padded = text + "=" * (-len(text) % 4)
    try:
        material = base64.urlsafe_b64decode(padded)
    except Exception as exc:
        raise KeyMaterialError(f"{label} is not valid base64url or hex") from exc

    if len(material) != KEY_LENGTH:
        raise KeyMaterialError(
            f"{label} decoded to {len(material)} bytes; expected {KEY_LENGTH}"
        )
    return material


def _collect_from_mapping(mapping: dict[str, str]) -> list[VersionedKey]:
    """Extract every ``ASSISTME_(KEK|BIK)_V<n>`` entry from a mapping."""
    keys: list[VersionedKey] = []
    for purpose, prefix in _ENV_PREFIX.items():
        for name, value in mapping.items():
            if not name.startswith(prefix):
                continue
            suffix = name[len(prefix):]
            if not suffix.isdigit():
                continue
            keys.append(
                VersionedKey(
                    purpose=purpose,
                    version=int(suffix),
                    material=_decode_key(value, name),
                )
            )
    return keys


def _load_key_file(path_value: str) -> list[VersionedKey]:
    path = Path(path_value)
    if not path.is_file():
        raise KeyMaterialError(f"ASSISTME_KEY_FILE points at a missing file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise KeyMaterialError(f"Could not parse key file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise KeyMaterialError("Key file must contain a JSON object")
    return _collect_from_mapping({str(k): str(v) for k, v in payload.items()})


def _derive_development_keys(secret_key: str) -> list[VersionedKey]:
    """Derive stable v1 keys from SECRET_KEY for local development only.

    HKDF-SHA256 with a distinct ``info`` per purpose guarantees the KEK and BIK
    are independent even though they share input material.
    """
    keys: list[VersionedKey] = []
    for purpose in KeyPurpose.ALL:
        material = HKDF(
            algorithm=hashes.SHA256(),
            length=KEY_LENGTH,
            salt=b"assistme-development-keyring-v1",
            info=f"assistme/{purpose}/v1".encode(),
        ).derive(secret_key.encode("utf-8"))
        keys.append(VersionedKey(purpose=purpose, version=1, material=material))
    return keys


def load_keyring(
    environ: dict[str, str] | None = None,
    *,
    secret_key: str | None = None,
    is_production: bool | None = None,
) -> KeyRing:
    """Build a :class:`KeyRing` from the runtime environment.

    Resolution order:
        1. ``ASSISTME_KEY_FILE`` (JSON object of key names to encoded material)
        2. ``ASSISTME_KEK_V*`` / ``ASSISTME_BIK_V*`` environment variables
        3. HKDF derivation from ``SECRET_KEY`` — development only

    Args:
        environ: Mapping to read from. Defaults to ``os.environ``.
        secret_key: Fallback derivation input. Defaults to the app settings.
        is_production: Overrides the environment's production flag, for tests.

    Raises:
        KeyMaterialError: In production when no explicit key material is found.
    """
    env = dict(os.environ if environ is None else environ)

    if is_production is None or secret_key is None:
        # Imported lazily so this module stays usable by offline tooling
        # (key generation, rotation scripts) that must not boot the app config.
        from core.config import settings

        if is_production is None:
            is_production = settings.IS_PRODUCTION
        if secret_key is None:
            secret_key = settings.SECRET_KEY

    keys: list[VersionedKey] = []

    key_file = env.get("ASSISTME_KEY_FILE")
    if key_file:
        keys.extend(_load_key_file(key_file))

    keys.extend(_collect_from_mapping(env))

    # De-duplicate: an explicit environment variable overrides the key file.
    deduped: dict[tuple[str, int], VersionedKey] = {}
    for key in keys:
        deduped[(key.purpose, key.version)] = key

    have_all = all(
        any(k.purpose == purpose for k in deduped.values())
        for purpose in KeyPurpose.ALL
    )

    if have_all:
        return KeyRing(list(deduped.values()), derived=False)

    if is_production:
        missing = [
            purpose.upper()
            for purpose in KeyPurpose.ALL
            if not any(k.purpose == purpose for k in deduped.values())
        ]
        raise KeyMaterialError(
            "Refusing to start in production without explicit key material. "
            f"Missing: {', '.join(missing)}. Provide ASSISTME_KEY_FILE or "
            "ASSISTME_KEK_V<n> / ASSISTME_BIK_V<n> environment variables. "
            "Generate keys with: python -m scripts.manage_keys generate"
        )

    derived = _derive_development_keys(secret_key)
    for key in derived:
        deduped.setdefault((key.purpose, key.version), key)
    return KeyRing(list(deduped.values()), derived=True)


# ----------------------------------------------------------------------
# Process-wide singleton
# ----------------------------------------------------------------------

_keyring: KeyRing | None = None
_keyring_lock = threading.Lock()


def get_keyring() -> KeyRing:
    """Return the process keyring, loading it on first use.

    Thread-safe and idempotent. Key material is loaded once and held in memory
    for the process lifetime; it is never written to disk or logged.
    """
    global _keyring
    if _keyring is None:
        with _keyring_lock:
            if _keyring is None:
                _keyring = load_keyring()
    return _keyring


def reset_keyring(keyring: KeyRing | None = None) -> None:
    """Replace or clear the process keyring. Intended for tests and rotation."""
    global _keyring
    with _keyring_lock:
        _keyring = keyring


def generate_key() -> str:
    """Generate a fresh base64url-encoded 32-byte key for operators."""
    return base64.urlsafe_b64encode(os.urandom(KEY_LENGTH)).decode("ascii").rstrip("=")
