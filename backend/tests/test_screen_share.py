"""Comprehensive test suite for Phase 4 Screen Sharing (Android MediaProjection & iOS ReplayKit).

Covers: start, stop, orientation changes, FLAG_SECURE security events, and status retrieval.
"""

import pytest
from httpx import AsyncClient

from tests.test_sessions import _create_session, _register


@pytest.mark.asyncio(loop_scope="session")
async def test_start_screen_share_android(client: AsyncClient) -> None:
    """Participant can start screen sharing with Android MediaProjection platform."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    resp = await client.post(
        f"/sessions/{session['id']}/screen-share/start",
        json={"platform": "android", "orientation": "portrait", "fps": 30},
        headers=helpee["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_screen_sharing"] is True
    assert data["platform"] == "android"
    assert data["screen_orientation"] == "portrait"
    assert data["participant_user_id"]


@pytest.mark.asyncio(loop_scope="session")
async def test_start_screen_share_ios(client: AsyncClient) -> None:
    """Participant can start screen sharing with iOS ReplayKit platform."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    resp = await client.post(
        f"/sessions/{session['id']}/screen-share/start",
        json={"platform": "ios", "orientation": "landscape"},
        headers=helpee["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_screen_sharing"] is True
    assert data["platform"] == "ios"
    assert data["screen_orientation"] == "landscape"


@pytest.mark.asyncio(loop_scope="session")
async def test_start_screen_share_invalid_platform(client: AsyncClient) -> None:
    """Invalid platform value is rejected with 422 validation error."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/screen-share/start",
        json={"platform": "windows", "orientation": "portrait"},
        headers=helper["headers"],
    )
    assert resp.status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_update_screen_share_orientation(client: AsyncClient) -> None:
    """Active screen sharer can update orientation between portrait and landscape."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    await client.post(
        f"/sessions/{session['id']}/screen-share/start",
        json={"platform": "android", "orientation": "portrait"},
        headers=helper["headers"],
    )

    resp = await client.post(
        f"/sessions/{session['id']}/screen-share/orientation",
        json={"orientation": "landscape"},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["screen_orientation"] == "landscape"


@pytest.mark.asyncio(loop_scope="session")
async def test_screen_share_security_event_flag_secure(client: AsyncClient) -> None:
    """Security events (FLAG_SECURE / protected app entered) activate security state."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    await client.post(
        f"/sessions/{session['id']}/screen-share/start",
        json={"platform": "android"},
        headers=helper["headers"],
    )

    # Report FLAG_SECURE protection event (e.g. banking app entered)
    resp = await client.post(
        f"/sessions/{session['id']}/screen-share/security-event",
        json={
            "event_type": "flag_secure_enabled",
            "detail": "Sensitive window active",
        },
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["is_flag_secure_active"] is True


@pytest.mark.asyncio(loop_scope="session")
async def test_screen_share_security_event_clear(client: AsyncClient) -> None:
    """Leaving protected app clears FLAG_SECURE protection state."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    await client.post(
        f"/sessions/{session['id']}/screen-share/start",
        json={"platform": "android"},
        headers=helper["headers"],
    )
    await client.post(
        f"/sessions/{session['id']}/screen-share/security-event",
        json={"event_type": "flag_secure_enabled"},
        headers=helper["headers"],
    )

    # Report leaving protected app
    resp = await client.post(
        f"/sessions/{session['id']}/screen-share/security-event",
        json={"event_type": "flag_secure_disabled"},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["is_flag_secure_active"] is False


@pytest.mark.asyncio(loop_scope="session")
async def test_stop_screen_share(client: AsyncClient) -> None:
    """Participant can stop screen sharing stream."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    await client.post(
        f"/sessions/{session['id']}/screen-share/start",
        json={"platform": "android"},
        headers=helper["headers"],
    )

    resp = await client.post(
        f"/sessions/{session['id']}/screen-share/stop",
        json={"reason": "user_stopped"},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["is_screen_sharing"] is False


@pytest.mark.asyncio(loop_scope="session")
async def test_get_screen_share_status(client: AsyncClient) -> None:
    """Other session participants can retrieve active screen share status."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    # Helpee starts sharing screen
    await client.post(
        f"/sessions/{session['id']}/screen-share/start",
        json={"platform": "ios", "orientation": "landscape"},
        headers=helpee["headers"],
    )

    # Helper checks status
    resp = await client.get(
        f"/sessions/{session['id']}/screen-share/status",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_screen_sharing"] is True
    assert data["platform"] == "ios"
    assert data["screen_orientation"] == "landscape"
