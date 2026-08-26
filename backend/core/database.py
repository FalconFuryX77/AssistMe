"""SQLAlchemy async engine, session factory, and declarative Base."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from core.config import settings

_engine_options: dict = {"echo": False}
if not settings.DATABASE_URL.startswith("sqlite"):
    _engine_options.update(
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
        pool_pre_ping=True,
    )

engine = create_async_engine(settings.DATABASE_URL, **_engine_options)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


async def create_tables() -> None:
    """Create all tables from ORM metadata (dev convenience)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def check_database_connection() -> None:
    """Raise if the database is unavailable; used by readiness probes."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency that yields a database session."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
