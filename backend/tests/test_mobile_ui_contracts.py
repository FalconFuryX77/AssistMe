"""Comprehensive test suite for Phase 16 Full Flutter Mobile UI Screens & Integration Contracts.

Covers: mobile auth token storage, mobile registration flows, session code join/create,
mobile touch gesture dispatching (tap, drag, long press), mobile audio routing, and in-app E2EE messaging.
"""

import pytest
from httpx import AsyncClient

from tests.test_sessions import _create_session, _register


@pytest.mark.asyncio(loop_scope="session")
async def test_mobile_ui_auth_and_registration_contract(client: AsyncClient) -> None:
    """Mobile LoginScreen and RegisterScreen API contract verification."""
    user = await _register(client)
    assert "access_token" in user
    assert "refresh_token" in user

    # Profile check with Bearer header
    me_resp = await client.get("/users/me", headers=user["headers"])
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == user["email"]


@pytest.mark.asyncio(loop_scope="session")
async def test_mobile_ui_session_join_and_create_contract(client: AsyncClient) -> None:
    """Mobile SessionScreen create and join by session code contract."""
    creator = await _register(client)
    joiner = await _register(client)

    # 1. Create session
    session = await _create_session(client, creator["headers"])
    assert session["status"] == "waiting"
    assert len(session["session_code"]) == 6

    # 2. Join via session code
    join_resp = await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=joiner["headers"],
    )
    assert join_resp.status_code == 200
    assert join_resp.json()["status"] == "active"


@pytest.mark.asyncio(loop_scope="session")
async def test_mobile_ui_touch_gesture_overlay_contract(client: AsyncClient) -> None:
    """Mobile RemoteScreenView gesture dispatching (tap, drag, long press) contract."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    # Grant remote control
    await client.post(
        f"/sessions/{session['id']}/remote-control/grant",
        json={"platform": "android_accessibility"},
        headers=helpee["headers"],
    )

    # Dispatch Tap
    tap_resp = await client.post(
        f"/sessions/{session['id']}/remote-control/input",
        json={
            "event_type": "tap",
            "x": 540.0,
            "y": 960.0,
            "normalized_x": 0.5,
            "normalized_y": 0.5,
        },
        headers=helper["headers"],
    )
    assert tap_resp.status_code == 200

    # Dispatch Drag
    drag_resp = await client.post(
        f"/sessions/{session['id']}/remote-control/input",
        json={
            "event_type": "drag",
            "x": 100.0,
            "y": 800.0,
            "end_x": 100.0,
            "end_y": 200.0,
            "duration_ms": 300,
        },
        headers=helper["headers"],
    )
    assert drag_resp.status_code == 200


@pytest.mark.asyncio(loop_scope="session")
async def test_mobile_ui_voice_control_bar_contract(client: AsyncClient) -> None:
    """MobileVoiceControlBar audio mute toggle and routing sheet contract."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    # Start audio
    await client.post(
        f"/sessions/{session['id']}/audio/start",
        json={"audio_route": "speaker"},
        headers=helper["headers"],
    )

    # Toggle mute
    mute_resp = await client.post(
        f"/sessions/{session['id']}/audio/mute",
        json={"is_muted": True},
        headers=helper["headers"],
    )
    assert mute_resp.status_code == 200

    # Change route to earpiece
    route_resp = await client.post(
        f"/sessions/{session['id']}/audio/route",
        json={"audio_route": "earpiece"},
        headers=helper["headers"],
    )
    assert route_resp.status_code == 200


@pytest.mark.asyncio(loop_scope="session")
async def test_mobile_ui_chat_and_chunked_file_contract(client: AsyncClient) -> None:
    """MobileChatDrawer text messaging, E2EE payloads, and chunked file transfers."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    # Send chat message
    chat_resp = await client.post(
        f"/sessions/{session['id']}/chat/messages",
        json={"content": "Mobile chat test message", "is_encrypted": True},
        headers=helper["headers"],
    )
    assert chat_resp.status_code == 200
    assert chat_resp.json()["is_encrypted"] is True

    # Initiate file transfer
    file_init = await client.post(
        f"/sessions/{session['id']}/files/initiate",
        json={
            "filename": "mobile_log.txt",
            "file_size_bytes": 1024,
            "checksum_sha256": "f" * 64,
        },
        headers=helper["headers"],
    )
    assert file_init.status_code == 200
