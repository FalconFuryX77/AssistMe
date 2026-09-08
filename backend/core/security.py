"""Security utilities: secret hashing and JWT token management.

Changes from the inherited implementation
-----------------------------------------
**Password hashing** moved from bcrypt to Argon2id with a keyed pepper (see
:mod:`core.crypto.hashing` for the reasoning, including the 72-byte truncation
defect that bcrypt 5 now raises on outright). Existing bcrypt and SHA-256 hashes
keep verifying and are upgraded opportunistically on next successful login.

**JWT claims** gained ``typ``, ``iss``, ``aud``, ``nbf`` and ``jti``. The
inherited token carried only ``sub``, ``exp`` and ``iat``. Backwards compatibility
is preserved: legacy tokens without audience/issuer claims decode seamlessly.
"""

from datetime import datetime, timedelta, timezone
import secrets
import uuid

from jose import JWTError, jwt

from core.config import settings
from core.crypto.hashing import (
    PEPPER_DOMAIN_PASSWORD,
    hash_secret,
    verify_secret,
)

#: Token type claim values. A token is only ever accepted for the purpose it
#: was minted for.
TOKEN_TYPE_ACCESS = "access"

#: Issuer and audience. Fixed strings rather than configuration, because a
#: deployment that changes them without coordinating both ends produces tokens
#: that verify nowhere, and the value carries no secrecy.
JWT_ISSUER = "assistme"
JWT_AUDIENCE = "assistme-api"

#: Tolerance for clock skew between the signer and the verifier.
LEEWAY_SECONDS = 30


# ---------------------------------------------------------------------------
# Secret hashing
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Hash a password with Argon2id over a peppered input."""
    return hash_secret(password, domain=PEPPER_DOMAIN_PASSWORD)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against an Argon2id or legacy bcrypt hash."""
    return verify_secret(
        plain_password, hashed_password, domain=PEPPER_DOMAIN_PASSWORD
    ).ok


def password_needs_upgrade(hashed_password: str) -> bool:
    """True when a stored hash uses a legacy scheme or stale parameters."""
    return not hashed_password.startswith("$argon2")


# ---------------------------------------------------------------------------
# JWT access tokens
# ---------------------------------------------------------------------------


def create_access_token(user_id: str) -> str:
    """Create a short-lived JWT access token.

    Claims:
        sub – subject (user id)
        typ – token purpose, checked on decode
        iss – issuer
        aud – intended audience
        iat – issued at
        nbf – not valid before
        exp – expiry
        jti – unique token id, for future revocation
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "typ": TOKEN_TYPE_ACCESS,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Decode and validate a JWT access token.

    Backwards-compatible: accepts new tokens with full claims (typ, iss, aud, nbf, jti)
    and legacy tokens (without aud/iss) seamlessly during migration.
    """
    try:
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
                audience=JWT_AUDIENCE,
                issuer=JWT_ISSUER,
                options={"leeway": LEEWAY_SECONDS},
            )
        except JWTError:
            # Fallback for legacy tokens without aud / iss claims
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
                options={"verify_aud": False, "verify_iss": False, "leeway": LEEWAY_SECONDS},
            )
    except JWTError:
        return None

    token_type = payload.get("typ")
    if token_type is not None and token_type != TOKEN_TYPE_ACCESS:
        return None

    return payload


# ---------------------------------------------------------------------------
# Refresh tokens (opaque random strings)
# ---------------------------------------------------------------------------


def create_refresh_token() -> str:
    """Generate a cryptographically secure random refresh token.

    384 bits of entropy. Stored only as a SHA-256 digest — see
    :class:`models.refresh_token.RefreshToken` for why a fast hash is the right
    choice for a secret of this entropy.
    """
    return secrets.token_urlsafe(48)
