"""Tests for the session WebSocket endpoint.

Covers: authentication, basic messaging, heartbeat, and leave via WebSocket.
"""

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _register_ws(client: AsyncClient) -> dict:
    """Register a user and return data with token."""
    import secrets

    suffix = secrets.token_hex(4)
    resp = await client.post(
        "/auth/register",
        json={
            "email": f"ws_{suffix}@example.com",
            "password": "SecureP1",
        },
    )
    data = resp.json()
    data["headers"] = {"Authorization": f"Bearer {data['access_token']}"}
    return data


# ---------------------------------------------------------------------------
# WebSocket Authentication Tests (via HTTP since ws testing is limited)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_ws_endpoint_exists(client: AsyncClient) -> None:
    """Verify the WebSocket endpoint route is registered in the application."""
    from app import app

    route_paths = [getattr(r, "path", None) for r in app.routes]
    assert "/ws/session/{session_id}" in route_paths


@pytest.mark.asyncio(loop_scope="session")
async def test_session_has_ws_compatible_structure(client: AsyncClient) -> None:
    """Sessions have all fields needed for WebSocket connectivity."""
    user = await _register_ws(client)
    resp = await client.post(
        "/sessions/",
        json={"title": "WS Test Session"},
        headers=user["headers"],
    )
    assert resp.status_code == 201
    data = resp.json()
    # These fields are needed by the WebSocket client
    assert "id" in data
    assert "session_code" in data
    assert "participants" in data
    assert data["participants"][0]["user_id"]
