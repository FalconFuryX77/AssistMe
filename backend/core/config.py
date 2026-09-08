"""Environment-driven application configuration.

The source tree contains safe development defaults only. Production values
must be supplied by the runtime (container environment, secret manager, or
Kubernetes Secret/ConfigMap); no public endpoint or credential belongs here.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / '.env')


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value is not None else default


def _csv_env(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings:
    """Central configuration for one API process."""

    APP_ENV: str = os.getenv("APP_ENV", "development").strip().lower()
    APP_NAME: str = os.getenv("APP_NAME", "AssistMe API")
    APP_VERSION: str = os.getenv("APP_VERSION", "1.0.0")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
    IS_PRODUCTION: bool = APP_ENV in {"production", "prod"}

    SECRET_KEY: str = os.getenv(
        "SECRET_KEY", "dev-secret-key-change-in-production-a1b2c3d4e5f6"
    )
    if IS_PRODUCTION and SECRET_KEY.startswith("dev-"):
        raise RuntimeError("SECRET_KEY must be configured in production")

    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = _env_int("ACCESS_TOKEN_EXPIRE_MINUTES", 30)
    REFRESH_TOKEN_EXPIRE_DAYS: int = _env_int("REFRESH_TOKEN_EXPIRE_DAYS", 7)

    # PostgreSQL is the production database. SQLite is for local development
    # and tests only; production schema changes belong in migrations.
    _default_db = f"sqlite+aiosqlite:///{Path(__file__).resolve().parent.parent / 'assistme.db'}"
    DATABASE_URL: str = os.getenv("DATABASE_URL", _default_db)
    DB_POOL_SIZE: int = _env_int("DB_POOL_SIZE", 10)
    DB_MAX_OVERFLOW: int = _env_int("DB_MAX_OVERFLOW", 20)
    DB_POOL_TIMEOUT_SECONDS: int = _env_int("DB_POOL_TIMEOUT_SECONDS", 30)
    # Below the 300 s idle timeout common to managed PostgreSQL and most
    # connection proxies, so stale connections are retired by the application
    # rather than discovered mid-request.
    DB_POOL_RECYCLE_SECONDS: int = _env_int("DB_POOL_RECYCLE_SECONDS", 280)
    DB_ECHO: bool = _env_bool("DB_ECHO", False)
    AUTO_CREATE_TABLES: bool = _env_bool("AUTO_CREATE_TABLES", not IS_PRODUCTION)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    # --- Machine learning runtime -------------------------------------
    # Directory holding versioned model artefacts. Read-only at runtime; the
    # training pipeline writes it out of band.
    ML_MODEL_DIR: str = os.getenv(
        "ML_MODEL_DIR", str(Path(__file__).resolve().parent.parent / "ml" / "artifacts")
    )
    # Master switch. When false, every decision falls back to the deterministic
    # rule engine — the behaviour the system must always be able to return to.
    ML_ENABLED: bool = _env_bool("ML_ENABLED", True)
    # Inference budget on the live-session hot path. A prediction slower than
    # this is abandoned and the rule fallback is used, so a pathological model
    # can never stall an assistance session.
    ML_INFERENCE_TIMEOUT_MS: int = _env_int("ML_INFERENCE_TIMEOUT_MS", 50)
    # Below this calibrated confidence the classifier abstains and the rule
    # engine decides. See docs/ML_METHODOLOGY.md for how it was chosen.
    ML_ABSTAIN_THRESHOLD: float = float(os.getenv("ML_ABSTAIN_THRESHOLD", "0.55"))
    # Persist every model-influenced decision for off-policy evaluation.
    ML_LOG_DECISIONS: bool = _env_bool("ML_LOG_DECISIONS", True)
    # Exploration rate for the contextual bandit. Zero disables exploration
    # entirely (pure exploitation), which is the correct setting if the
    # deployment cannot tolerate any randomised action selection.
    ML_BANDIT_EXPLORATION: float = float(os.getenv("ML_BANDIT_EXPLORATION", "0.10"))

    PASSWORD_MIN_LENGTH: int = _env_int("PASSWORD_MIN_LENGTH", 8)

    STUN_SERVERS: list[str] = _csv_env(
        "STUN_SERVERS",
        [
            os.getenv("STUN_SERVER_1", "stun:stun.l.google.com:19302"),
            os.getenv("STUN_SERVER_2", "stun:stun1.l.google.com:19302"),
        ],
    )
    TURN_SERVER_URL: str | None = os.getenv("TURN_SERVER_URL")
    TURN_SERVER_USERNAME: str | None = os.getenv("TURN_SERVER_USERNAME")
    TURN_SERVER_CREDENTIAL: str | None = os.getenv("TURN_SERVER_CREDENTIAL")
    METERED_API_KEY: str | None = os.getenv("METERED_API_KEY")
    METERED_DOMAIN: str | None = os.getenv("METERED_DOMAIN", "assistme.metered.live")

    # These describe the public edge gateway, never an internal service name.
    ALLOWED_ORIGINS: list[str] = _csv_env(
        "ALLOWED_ORIGINS", ["*"] if not IS_PRODUCTION else []
    )
    PUBLIC_API_BASE_URL: str | None = os.getenv("PUBLIC_API_BASE_URL")
    PUBLIC_WS_BASE_URL: str | None = os.getenv("PUBLIC_WS_BASE_URL")
    PUBLIC_TURN_URL: str | None = os.getenv("PUBLIC_TURN_URL")
    PUBLIC_STUN_URLS: list[str] | None = (
        _csv_env("PUBLIC_STUN_URLS", []) if os.getenv("PUBLIC_STUN_URLS") else None
    )


settings = Settings()
