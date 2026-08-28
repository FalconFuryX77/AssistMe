"""Shared test fixtures for the AssistMe backend test suite."""

import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.database import Base, get_db

# ---------------------------------------------------------------------------
# In-memory SQLite for tests (isolated per session)
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite://"  # in-memory

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
test_session_factory = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)




@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    """Create all tables for each test and drop after."""
    from core.rate_limiter import (
        bootstrap_rate_limiter,
        global_rate_limiter,
        help_call_rate_limiter,
        pairing_rate_limiter,
        reclaim_rate_limiter,
    )

    global_rate_limiter.requests.clear()
    pairing_rate_limiter.requests.clear()
    reclaim_rate_limiter.requests.clear()
    bootstrap_rate_limiter.requests.clear()
    help_call_rate_limiter.requests.clear()

    import models  # noqa: F401

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session(setup_database) -> AsyncGenerator[AsyncSession, None]:
    """Yield a fresh database session for each test."""
    async with test_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Yield an async HTTP test client with the test DB injected."""
    from app import app

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def registered_user(client: AsyncClient) -> dict:
    """Register a test user and return the response data (tokens + display_name)."""
    response = await client.post(
        "/auth/device",
        json={
            "device_fingerprint": "assistme-test-device-fp-fixture-01",
            "display_name": "Test User",
        },
    )
    data = response.json()
    return data


@pytest_asyncio.fixture
async def auth_headers(registered_user: dict) -> dict[str, str]:
    """Return Authorization headers for the registered test user."""
    return {"Authorization": f"Bearer {registered_user['access_token']}"}


@pytest_asyncio.fixture
async def second_user(client: AsyncClient) -> dict:
    """Register a second test user for contact testing."""
    response = await client.post(
        "/auth/device",
        json={
            "device_fingerprint": "assistme-test-device-fp-fixture-02",
            "display_name": "Second User",
        },
    )
    data = response.json()
    return data

