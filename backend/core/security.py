"""Security utilities: password hashing and JWT token management."""

from datetime import datetime, timedelta, timezone
import secrets

import bcrypt
from jose import JWTError, jwt

from core.config import settings

# ---------------------------------------------------------------------------
# Password hashing (bcrypt — direct usage for compatibility)
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its bcrypt hash."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


# ---------------------------------------------------------------------------
# JWT access tokens
# ---------------------------------------------------------------------------


def create_access_token(user_id: str) -> str:
    """Create a short-lived JWT access token.

    Claims:
        sub  – user ID (UUID as string)
        exp  – expiration timestamp
        iat  – issued-at timestamp
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": now,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Decode and validate a JWT access token.

    Returns the payload dict on success, or None if the token is
    invalid / expired.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# Refresh tokens (opaque random strings)
# ---------------------------------------------------------------------------


def create_refresh_token() -> str:
    """Generate a cryptographically secure random refresh token."""
    return secrets.token_urlsafe(48)
