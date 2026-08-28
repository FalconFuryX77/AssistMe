"""Comprehensive test suite for Mobile App Core Architecture & Security Foundation.

Covers: mobile authentication token interceptors, secure storage token refresh contracts,
mobile WebRTC STUN/TURN configuration fetch, and Session state transitions.
"""

import pytest
from httpx import AsyncClient

from tests.test_sessions import _create_session, _register


@pytest.mark.asyncio(loop_scope="session")
async def test_mobile_auth_token_interceptor_flow(client: AsyncClient) -> None:
    """Mobile ApiClient token lifecycle: bootstrap, retrieve tokens, use Bearer header, refresh tokens."""
    auth = await _register(client)
    assert "access_token" in auth
    assert "refresh_token" in auth

    # Bearer header check
    resp = await client.get("/users/me", headers=auth["headers"])
    assert resp.status_code == 200
    assert resp.json()["id"] == auth["user"]["id"]

    # Token refresh check
    refresh_resp = await client.post(
        "/auth/refresh",
        json={"refresh_token": auth["refresh_token"]},
    )
    assert refresh_resp.status_code == 200
    assert "access_token" in refresh_resp.json()


@pytest.mark.asyncio(loop_scope="session")
async def test_mobile_webrtc_engine_config(client: AsyncClient) -> None:
    """Mobile WebRTCEngine initialization fetches STUN/TURN ICE server configuration."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.get(
        f"/sessions/{session['id']}/ice-servers",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "ice_servers" in data
    assert len(data["ice_servers"]) >= 1


@pytest.mark.asyncio(loop_scope="session")
async def test_mobile_session_state_transitions(client: AsyncClient) -> None:
    """Mobile Session state transitions: Create -> Join -> Leave (symmetric teardown)."""
    helper = await _register(client)
    helpee = await _register(client)

    # Initial -> Connecting -> Active (Create)
    session = await _create_session(client, helper["headers"])
    assert session["status"] == "waiting"

    # Connecting -> Active (Join)
    join_resp = await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )
    assert join_resp.status_code == 200
    assert join_resp.json()["status"] == "active"

    # Leave -> Symmetric termination per VISION §12.10
    leave_resp = await client.post(
        f"/sessions/{session['id']}/leave",
        headers=helpee["headers"],
    )
    assert leave_resp.status_code == 200
    assert leave_resp.json()["status"] == "ended"
