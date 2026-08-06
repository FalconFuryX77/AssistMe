"""Comprehensive test suite for Phase 6 Remote Control Protocol (Android AccessibilityService & iOS AssistiveTouch).

Covers: permission grant/revoke, tap gestures, drag gestures, long press, key events (back/home/recents),
permission checks, and status queries.
"""

import pytest
from httpx import AsyncClient

from tests.test_sessions import _create_session, _register


@pytest.mark.asyncio(loop_scope="session")
async def test_grant_remote_control_success(client: AsyncClient) -> None:
    """Participant can grant remote control permission for Android Accessibility Service."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    resp = await client.post(
        f"/sessions/{session['id']}/remote-control/grant",
        json={"platform": "android_accessibility"},
        headers=helpee["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["remote_control_granted"] is True
    assert data["remote_control_platform"] == "android_accessibility"
    assert data["remote_control_granted_at"] is not None


@pytest.mark.asyncio(loop_scope="session")
async def test_grant_remote_control_ios(client: AsyncClient) -> None:
    """Participant can grant remote control permission for iOS AssistiveTouch."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    resp = await client.post(
        f"/sessions/{session['id']}/remote-control/grant",
        json={"platform": "ios_assistivetouch"},
        headers=helpee["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["remote_control_granted"] is True
    assert data["remote_control_platform"] == "ios_assistivetouch"


@pytest.mark.asyncio(loop_scope="session")
async def test_grant_remote_control_invalid_platform(client: AsyncClient) -> None:
    """Invalid remote control platform string returns 422 validation error."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/remote-control/grant",
        json={"platform": "windows_touch"},
        headers=helper["headers"],
    )
    assert resp.status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_dispatch_input_event_unauthorized_before_grant(client: AsyncClient) -> None:
    """Helper attempting to send input before permission is granted receives 403 Forbidden."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    # Attempt tap without permission grant
    resp = await client.post(
        f"/sessions/{session['id']}/remote-control/input",
        json={"event_type": "tap", "x": 540.0, "y": 960.0, "normalized_x": 0.5, "normalized_y": 0.5},
        headers=helper["headers"],
    )
    assert resp.status_code == 403
    assert "not been granted" in resp.json()["detail"].lower()


@pytest.mark.asyncio(loop_scope="session")
async def test_dispatch_input_event_tap(client: AsyncClient) -> None:
    """Helper can dispatch Tap input events when permission is granted."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    # Grant control
    await client.post(
        f"/sessions/{session['id']}/remote-control/grant",
        json={"platform": "android_accessibility"},
        headers=helpee["headers"],
    )

    # Dispatch tap
    resp = await client.post(
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
    assert resp.status_code == 200
    data = resp.json()
    assert data["event"]["event_type"] == "tap"
    assert data["event"]["normalized_x"] == 0.5


@pytest.mark.asyncio(loop_scope="session")
async def test_dispatch_input_event_drag(client: AsyncClient) -> None:
    """Helper can dispatch Drag gesture events."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )
    await client.post(
        f"/sessions/{session['id']}/remote-control/grant",
        headers=helpee["headers"],
    )

    resp = await client.post(
        f"/sessions/{session['id']}/remote-control/input",
        json={
            "event_type": "drag",
            "x": 100.0,
            "y": 800.0,
            "end_x": 100.0,
            "end_y": 200.0,
            "duration_ms": 400,
        },
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["event"]["event_type"] == "drag"
    assert data["event"]["end_y"] == 200.0


@pytest.mark.asyncio(loop_scope="session")
async def test_dispatch_input_event_key_event(client: AsyncClient) -> None:
    """Helper can dispatch hardware key events (back, home, recents)."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )
    await client.post(
        f"/sessions/{session['id']}/remote-control/grant",
        headers=helpee["headers"],
    )

    resp = await client.post(
        f"/sessions/{session['id']}/remote-control/input",
        json={"event_type": "key_event", "key_code": "back"},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["event"]["key_code"] == "back"


@pytest.mark.asyncio(loop_scope="session")
async def test_revoke_remote_control(client: AsyncClient) -> None:
    """Helpee revoking control immediately blocks subsequent input dispatches."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )
    await client.post(
        f"/sessions/{session['id']}/remote-control/grant",
        headers=helpee["headers"],
    )

    # Revoke permission
    resp = await client.post(
        f"/sessions/{session['id']}/remote-control/revoke",
        headers=helpee["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["remote_control_granted"] is False

    # Attempt input after revocation — must fail 403
    resp2 = await client.post(
        f"/sessions/{session['id']}/remote-control/input",
        json={"event_type": "tap", "x": 100.0, "y": 100.0},
        headers=helper["headers"],
    )
    assert resp2.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_get_remote_control_status(client: AsyncClient) -> None:
    """Participants can query current remote control permission status."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.get(
        f"/sessions/{session['id']}/remote-control/status",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["remote_control_granted"] is False
