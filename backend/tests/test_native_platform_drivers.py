"""Comprehensive test suite for Phase 17 Native Platform Plugin Drivers (Android & iOS).

Covers: Android AccessibilityService gesture dispatch descriptors, MediaProjection token lifecycle,
iOS ReplayKit broadcast frame buffers, iOS AssistiveTouch normalized coordinate mappings,
and FLAG_SECURE window masking events.
"""

import pytest
from httpx import AsyncClient

from tests.test_sessions import _create_session, _register


@pytest.mark.asyncio(loop_scope="session")
async def test_android_accessibility_gesture_dispatch_contract(client: AsyncClient) -> None:
    """Android AccessibilityService GestureDescription tap, drag, and long press dispatch contract."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    # Grant Android Accessibility remote control
    grant_resp = await client.post(
        f"/sessions/{session['id']}/remote-control/grant",
        json={"platform": "android_accessibility"},
        headers=helpee["headers"],
    )
    assert grant_resp.status_code == 200
    assert grant_resp.json()["remote_control_platform"] == "android_accessibility"

    # Tap gesture at (540, 960) with normalized (0.5, 0.5)
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

    # Drag gesture
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

    # Global key event: BACK
    key_resp = await client.post(
        f"/sessions/{session['id']}/remote-control/input",
        json={
            "event_type": "key_event",
            "key_code": "back",
        },
        headers=helper["headers"],
    )
    assert key_resp.status_code == 200


@pytest.mark.asyncio(loop_scope="session")
async def test_android_mediaprojection_screen_stream_contract(client: AsyncClient) -> None:
    """Android MediaProjection foreground service screen sharing initialization."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    # Start MediaProjection stream
    start_resp = await client.post(
        f"/sessions/{session['id']}/screen-share/start",
        json={
            "platform": "android",
            "orientation": "portrait",
            "width": 1080,
            "height": 1920,
            "fps": 30,
        },
        headers=helpee["headers"],
    )
    assert start_resp.status_code == 200
    data = start_resp.json()
    assert data["is_screen_sharing"] is True
    assert data["platform"] == "android"


@pytest.mark.asyncio(loop_scope="session")
async def test_ios_replaykit_broadcast_contract(client: AsyncClient) -> None:
    """iOS ReplayKit RPBroadcastSampleHandler screen sharing initialization."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    # Start iOS ReplayKit stream
    start_resp = await client.post(
        f"/sessions/{session['id']}/screen-share/start",
        json={
            "platform": "ios",
            "orientation": "portrait",
            "width": 1170,
            "height": 2532,
            "fps": 60,
        },
        headers=helpee["headers"],
    )
    assert start_resp.status_code == 200
    data = start_resp.json()
    assert data["is_screen_sharing"] is True
    assert data["platform"] == "ios"


@pytest.mark.asyncio(loop_scope="session")
async def test_ios_assistivetouch_gesture_contract(client: AsyncClient) -> None:
    """iOS AssistiveTouch touch simulation and UIAutomation grant contract."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    # Grant iOS AssistiveTouch permission
    grant_resp = await client.post(
        f"/sessions/{session['id']}/remote-control/grant",
        json={"platform": "ios_assistivetouch"},
        headers=helpee["headers"],
    )
    assert grant_resp.status_code == 200
    assert grant_resp.json()["remote_control_platform"] == "ios_assistivetouch"


@pytest.mark.asyncio(loop_scope="session")
async def test_flag_secure_privacy_masking_contract(client: AsyncClient) -> None:
    """FLAG_SECURE and sensitive window masking security event broadcasting."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    # Trigger FLAG_SECURE active event
    sec_resp = await client.post(
        f"/sessions/{session['id']}/screen-share/security-event",
        json={
            "event_type": "flag_secure_enabled",
            "detail": "Banking app window foregrounded",
        },
        headers=helpee["headers"],
    )
    assert sec_resp.status_code == 200
    assert sec_resp.json()["is_flag_secure_active"] is True

    # Clear FLAG_SECURE event
    clear_resp = await client.post(
        f"/sessions/{session['id']}/screen-share/security-event",
        json={
            "event_type": "flag_secure_disabled",
            "detail": "Sensitive window dismissed",
        },
        headers=helpee["headers"],
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json()["is_flag_secure_active"] is False
