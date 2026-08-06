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


settings = Settings()
