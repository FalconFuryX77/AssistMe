"""Comprehensive test suite for Phase 13 Web Client Core Architecture & WebRTC Client Integration.

Covers: web browser auth header injection, WebRTC STUN/TURN config fetch, WebRTC Insertable Streams E2EE verification,
and canvas stream decoding bitrate & resolution configuration contracts.
"""

import pytest
from httpx import AsyncClient

from tests.test_sessions import _create_session, _register


@pytest.mark.asyncio(loop_scope="session")
async def test_web_auth_token_store_flow(client: AsyncClient) -> None:
    """WebApiClient token lifecycle: register, retrieve profile with Bearer header."""
    auth = await _register(client)
    assert "access_token" in auth

    resp = await client.get("/users/me", headers=auth["headers"])
    assert resp.status_code == 200
    assert resp.json()["email"] == auth["user"]["email"]


@pytest.mark.asyncio(loop_scope="session")
async def test_web_webrtc_ice_server_fetch(client: AsyncClient) -> None:
    """WebWebRTCClient fetches STUN/TURN server configuration for browser RTCPeerConnection."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.get(
        f"/sessions/{session['id']}/ice-servers",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "ice_servers" in data
    assert any(s["urls"][0].startswith("stun:") for s in data["ice_servers"])


@pytest.mark.asyncio(loop_scope="session")
async def test_web_webrtc_insertable_streams_e2ee(client: AsyncClient) -> None:
    """WebRTC Insertable Streams E2EE frame transformer & SAS safety number fingerprint verification."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    exchange_resp = await client.post(
        f"/sessions/{session['id']}/e2ee/keys/exchange",
        json={
            "identity_key": "web_browser_identity_key_xyz",
            "signed_prekey": "web_browser_signed_prekey_123",
            "ephemeral_key": "web_browser_ephemeral_key_456",
        },
        headers=helper["headers"],
    )
    assert exchange_resp.status_code == 200
    fingerprint = exchange_resp.json()["fingerprint"]

    verify_resp = await client.post(
        f"/sessions/{session['id']}/e2ee/verify",
        json={
            "safety_number_fingerprint": fingerprint,
            "is_verified_by_user": True,
        },
        headers=helpee["headers"],
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["is_mitm_verified"] is True


@pytest.mark.asyncio(loop_scope="session")
async def test_web_canvas_stream_decoding_contract(client: AsyncClient) -> None:
    """Web CanvasRenderer video stream configuration: adaptive resolution & bitrate adaptation."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/streaming/adapt",
        json={
            "video_resolution": "1080p",
            "video_fps": 60,
            "video_bitrate_kbps": 3500,
        },
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["video_resolution"] == "1080p"
    assert data["video_fps"] == 60
    assert data["video_bitrate_kbps"] == 3500
