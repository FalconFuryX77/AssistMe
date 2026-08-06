"""Comprehensive tests for the authentication API.

Covers: registration, login, token refresh, logout, edge cases, and security.
"""

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Registration Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_register_success(client: AsyncClient) -> None:
    """Registration with valid data returns 201 with tokens."""
    response = await client.post(
        "/auth/register",
        json={
            "email": "newuser@example.com",
            "password": "SecureP1",
            "display_name": "New User",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["token_type"] == "bearer"
    assert data["access_token"]
    assert data["refresh_token"]


@pytest.mark.asyncio(loop_scope="session")
async def test_register_duplicate_email(client: AsyncClient) -> None:
    """Registering with an already-used email returns 400."""
    payload = {"email": "duplicate@example.com", "password": "SecureP1"}
    await client.post("/auth/register", json=payload)
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"].lower()


@pytest.mark.asyncio(loop_scope="session")
async def test_register_invalid_email(client: AsyncClient) -> None:
    """Registration with a malformed email returns 422."""
    response = await client.post(
        "/auth/register",
        json={"email": "not-an-email", "password": "SecureP1"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_register_weak_password_too_short(client: AsyncClient) -> None:
    """Password shorter than 8 characters is rejected."""
    response = await client.post(
        "/auth/register",
        json={"email": "weak1@example.com", "password": "Ab1"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_register_weak_password_no_uppercase(client: AsyncClient) -> None:
    """Password without uppercase letter is rejected."""
    response = await client.post(
        "/auth/register",
        json={"email": "weak2@example.com", "password": "alllower1"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_register_weak_password_no_digit(client: AsyncClient) -> None:
    """Password without a digit is rejected."""
    response = await client.post(
        "/auth/register",
        json={"email": "weak3@example.com", "password": "NoDigits"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Login Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_login_success(client: AsyncClient, registered_user: dict) -> None:
    """Login with correct credentials returns tokens."""
    response = await client.post(
        "/auth/login",
        json={
            "email": registered_user["email"],
            "password": registered_user["password"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio(loop_scope="session")
async def test_login_wrong_password(client: AsyncClient, registered_user: dict) -> None:
    """Login with wrong password returns 401."""
    response = await client.post(
        "/auth/login",
        json={"email": registered_user["email"], "password": "WrongPass1"},
    )
    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower()


@pytest.mark.asyncio(loop_scope="session")
async def test_login_nonexistent_user(client: AsyncClient) -> None:
    """Login with unregistered email returns 401."""
    response = await client.post(
        "/auth/login",
        json={"email": "noone@example.com", "password": "SecureP1"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Token Refresh Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_refresh_token_success(client: AsyncClient, registered_user: dict) -> None:
    """Valid refresh token returns a new access token."""
    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": registered_user["refresh_token"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio(loop_scope="session")
async def test_refresh_token_invalid(client: AsyncClient) -> None:
    """Invalid refresh token returns 401."""
    response = await client.post(
        "/auth/refresh",
        json={"refresh_token": "totally-invalid-token"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Logout Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_logout_success(client: AsyncClient) -> None:
    """Logout revokes the refresh token."""
    # Register a fresh user for this test
    reg = await client.post(
        "/auth/register",
        json={"email": "logouttest@example.com", "password": "SecureP1"},
    )
    tokens = reg.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    response = await client.post(
        "/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers=headers,
    )
    assert response.status_code == 200
    assert "logged out" in response.json()["detail"].lower()

    # Verify the refresh token is now revoked
    refresh_resp = await client.post(
        "/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refresh_resp.status_code == 401


# ---------------------------------------------------------------------------
# Security Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_invalid_jwt_rejected(client: AsyncClient) -> None:
    """A crafted/invalid JWT is rejected by protected endpoints."""
    response = await client.get(
        "/users/me",
        headers={"Authorization": "Bearer invalid.jwt.token"},
    )
    assert response.status_code in (401, 403)


@pytest.mark.asyncio(loop_scope="session")
async def test_missing_auth_header_rejected(client: AsyncClient) -> None:
    """Protected endpoints without Authorization header return 401/403."""
    response = await client.get("/users/me")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio(loop_scope="session")
async def test_sql_injection_in_login(client: AsyncClient) -> None:
    """SQL injection attempt in email field doesn't cause server error."""
    response = await client.post(
        "/auth/login",
        json={
            "email": "' OR 1=1 --@example.com",
            "password": "anything",
        },
    )
    # Should be 401 (not found) or 422 (validation), NOT 500
    assert response.status_code in (401, 422)
