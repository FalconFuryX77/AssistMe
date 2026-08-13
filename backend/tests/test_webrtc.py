"""Comprehensive tests for WebRTC signaling and ICE configuration.

Covers: ICE servers endpoint, authorization, schema validation, and TURN server configuration.
"""

import pytest
from httpx import AsyncClient

from api.schemas.webrtc import ICECandidateMessage, SDPAnswerMessage, SDPOfferMessage
from api.services.webrtc_service import WebRTCService
from core.config import settings
from tests.test_sessions import _create_session, _register


@pytest.mark.asyncio(loop_scope="session")
async def test_get_ice_servers_success(client: AsyncClient) -> None:
    """Session participants can retrieve RTCIceServer configuration."""
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
    # Verify default Google STUN server is present
    urls = data["ice_servers"][0]["urls"]
    assert "stun:stun.l.google.com:19302" in urls or "stun:stun.l.google.com:19302" in str(urls)


@pytest.mark.asyncio(loop_scope="session")
async def test_get_ice_servers_unauthorized(client: AsyncClient) -> None:
    """Accessing ice-servers without authentication returns 401/403."""
    resp = await client.get("/sessions/some-session-id/ice-servers")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio(loop_scope="session")
async def test_get_ice_servers_non_participant(client: AsyncClient) -> None:
    """Non-participants cannot retrieve session ice-servers."""
    helper = await _register(client)
    outsider = await _register(client)

    session = await _create_session(client, helper["headers"])

    resp = await client.get(
        f"/sessions/{session['id']}/ice-servers",
        headers=outsider["headers"],
    )
    assert resp.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_webrtc_service_turn_config(monkeypatch) -> None:
    """WebRTCService includes TURN server credentials when configured."""
    # Patch the settings object that the service module actually references
    # (may differ from our module-level import after module reloads in other tests)
    import api.services.webrtc_service as svc_mod
    svc_settings = svc_mod.settings
    monkeypatch.setattr(svc_settings, "TURN_SERVER_URL", "turn:turn.example.com:3478")
    monkeypatch.setattr(svc_settings, "TURN_SERVER_USERNAME", "testuser")
    monkeypatch.setattr(svc_settings, "TURN_SERVER_CREDENTIAL", "testpass")
    # Ensure PUBLIC_TURN_URL is cleared so the legacy TURN_SERVER_URL path is used
    monkeypatch.setattr(svc_settings, "PUBLIC_TURN_URL", None)

    ice_config = WebRTCService.get_ice_servers()
    assert len(ice_config.ice_servers) == 2
    turn_entry = ice_config.ice_servers[1]
    assert turn_entry.urls == "turn:turn.example.com:3478"
    assert turn_entry.username == "testuser"
    assert turn_entry.credential == "testpass"


def test_webrtc_sdp_offer_schema_validation() -> None:
    """SDPOfferMessage schema validates offer payloads correctly."""
    offer = SDPOfferMessage(sdp="v=0\r\no=- 123456...", target_user_id="user-123")
    assert offer.type == "offer"
    assert offer.sdp.startswith("v=0")
    assert offer.target_user_id == "user-123"


def test_webrtc_sdp_answer_schema_validation() -> None:
    """SDPAnswerMessage schema validates answer payloads correctly."""
    answer = SDPAnswerMessage(sdp="v=0\r\no=- 654321...", target_user_id="user-456")
    assert answer.type == "answer"
    assert answer.sdp.startswith("v=0")
    assert answer.target_user_id == "user-456"


def test_webrtc_ice_candidate_schema_validation() -> None:
    """ICECandidateMessage schema validates candidate payloads correctly."""
    cand = ICECandidateMessage(
        candidate={"candidate": "candidate:1 1 UDP 2122194687...", "sdpMid": "0"},
        target_user_id="user-789",
    )
    assert cand.type == "candidate"
    assert "candidate" in cand.candidate
    assert cand.target_user_id == "user-789"
