"""Tests for the user profile API.

Covers: profile retrieval, updates, and unauthorized access.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio(loop_scope="session")
async def test_get_profile_success(
    client: AsyncClient,
    registered_user: dict,
    auth_headers: dict,
) -> None:
    """Authenticated user can retrieve their own profile."""
    response = await client.get("/users/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["display_name"] == registered_user.get("display_name", "Test User")
    assert data["is_active"] is True
    assert "created_at" in data


@pytest.mark.asyncio(loop_scope="session")
async def test_update_profile_display_name(
    client: AsyncClient,
    auth_headers: dict,
) -> None:
    """Updating display_name persists the change."""
    response = await client.patch(
        "/users/me",
        json={"display_name": "Updated Name"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["display_name"] == "Updated Name"

    # Verify it persisted
    get_resp = await client.get("/users/me", headers=auth_headers)
    assert get_resp.json()["display_name"] == "Updated Name"


@pytest.mark.asyncio(loop_scope="session")
async def test_get_profile_unauthorized(client: AsyncClient) -> None:
    """GET /users/me without auth returns 401/403."""
    response = await client.get("/users/me")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio(loop_scope="session")
async def test_update_profile_unauthorized(client: AsyncClient) -> None:
    """PATCH /users/me without auth returns 401/403."""
    response = await client.patch(
        "/users/me", json={"display_name": "Hacker"}
    )
    assert response.status_code in (401, 403)
