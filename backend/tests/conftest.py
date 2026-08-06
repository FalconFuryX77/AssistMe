"""Shared test fixtures for the AssistMe backend test suite."""

import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.database import Base, get_db

# ---------------------------------------------------------------------------
# In-memory SQLite for tests (isolated per session)
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite://"  # in-memory

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
test_session_factory = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def setup_database():
    """Create all tables once for the test session."""
    # Import models so Base.metadata knows about them
    import models  # noqa: F401

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(loop_scope="session")
async def db_session(setup_database) -> AsyncGenerator[AsyncSession, None]:
    """Yield a fresh database session for each test, rolling back after."""
    async with test_session_factory() as session:
        yield session
        # Clean up all data after each test
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(table.delete())
        await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
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


@pytest_asyncio.fixture(loop_scope="session")
async def registered_user(client: AsyncClient) -> dict:
    """Register a test user and return the response data (tokens + email)."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "testuser@example.com",
            "password": "TestPass1",
            "display_name": "Test User",
        },
    )
    data = response.json()
    data["email"] = "testuser@example.com"
    data["password"] = "TestPass1"
    return data


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers(registered_user: dict) -> dict[str, str]:
    """Return Authorization headers for the registered test user."""
    return {"Authorization": f"Bearer {registered_user['access_token']}"}


@pytest_asyncio.fixture(loop_scope="session")
async def second_user(client: AsyncClient) -> dict:
    """Register a second test user for contact testing."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "seconduser@example.com",
            "password": "TestPass2",
            "display_name": "Second User",
        },
    )
    data = response.json()
    data["email"] = "seconduser@example.com"
    return data
