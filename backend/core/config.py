"""Application configuration loaded from environment variables."""

import os
from pathlib import Path


class Settings:
    """Central configuration for the AssistMe backend."""

    # --- JWT ---
    SECRET_KEY: str = os.getenv(
        "SECRET_KEY",
        "dev-secret-key-change-in-production-a1b2c3d4e5f6",
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- Database ---
    # Default: SQLite for local development.  Set DATABASE_URL env var for PostgreSQL.
    _default_db = f"sqlite+aiosqlite:///{Path(__file__).resolve().parent.parent / 'assistme.db'}"
    DATABASE_URL: str = os.getenv("DATABASE_URL", _default_db)

    # --- Password policy ---
    PASSWORD_MIN_LENGTH: int = 8

    # --- WebRTC STUN / TURN ---
    STUN_SERVERS: list[str] = [
        os.getenv("STUN_SERVER_1", "stun:stun.l.google.com:19302"),
        os.getenv("STUN_SERVER_2", "stun:stun1.l.google.com:19302"),
    ]
    TURN_SERVER_URL: str | None = os.getenv("TURN_SERVER_URL", None)
    TURN_SERVER_USERNAME: str | None = os.getenv("TURN_SERVER_USERNAME", None)
    TURN_SERVER_CREDENTIAL: str | None = os.getenv("TURN_SERVER_CREDENTIAL", None)


settings = Settings()
