"""Comprehensive test suite for Phase 5 Voice Communication.

Covers: audio call start/stop, mute/unmute, audio routing (speaker, earpiece, bluetooth, headset),
network degradation reporting, and status queries.
"""

import pytest
from httpx import AsyncClient

from tests.test_sessions import _create_session, _register


@pytest.mark.asyncio(loop_scope="session")
async def test_start_audio_call_success(client: AsyncClient) -> None:
    """Participant can start/join an audio call in a session."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    resp = await client.post(
        f"/sessions/{session['id']}/audio/start",
        json={"is_muted": False, "audio_route": "speaker"},
        headers=helpee["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_in_audio_call"] is True
    assert data["is_audio_muted"] is False
    assert data["audio_route"] == "speaker"
    assert data["audio_quality"] == "high"


@pytest.mark.asyncio(loop_scope="session")
async def test_start_audio_call_bluetooth_route(client: AsyncClient) -> None:
    """Participant can initiate audio call directly routed to a Bluetooth device."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/audio/start",
        json={"is_muted": True, "audio_route": "bluetooth"},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_in_audio_call"] is True
    assert data["is_audio_muted"] is True
    assert data["audio_route"] == "bluetooth"


@pytest.mark.asyncio(loop_scope="session")
async def test_start_audio_call_invalid_route(client: AsyncClient) -> None:
    """Invalid audio_route string returns 422 validation error."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/audio/start",
        json={"audio_route": "subwoofer"},
        headers=helper["headers"],
    )
    assert resp.status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_toggle_audio_mute(client: AsyncClient) -> None:
    """Participant in active audio call can mute and unmute their microphone."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    # Start audio call
    await client.post(
        f"/sessions/{session['id']}/audio/start",
        json={"is_muted": False},
        headers=helper["headers"],
    )

    # Mute microphone
    resp = await client.post(
        f"/sessions/{session['id']}/audio/mute",
        json={"is_muted": True},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["is_audio_muted"] is True

    # Unmute microphone
    resp2 = await client.post(
        f"/sessions/{session['id']}/audio/mute",
        json={"is_muted": False},
        headers=helper["headers"],
    )
    assert resp2.status_code == 200
    assert resp2.json()["is_audio_muted"] is False


@pytest.mark.asyncio(loop_scope="session")
async def test_toggle_audio_mute_not_in_call(client: AsyncClient) -> None:
    """Toggling mute when not in an active audio call returns 400 error."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/audio/mute",
        json={"is_muted": True},
        headers=helper["headers"],
    )
    assert resp.status_code == 400


@pytest.mark.asyncio(loop_scope="session")
async def test_change_audio_route_earpiece_and_headset(client: AsyncClient) -> None:
    """Participant can dynamically change audio output routing between speaker, earpiece, and headset."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    await client.post(
        f"/sessions/{session['id']}/audio/start",
        json={"audio_route": "speaker"},
        headers=helper["headers"],
    )

    # Switch to earpiece
    resp1 = await client.post(
        f"/sessions/{session['id']}/audio/route",
        json={"audio_route": "earpiece"},
        headers=helper["headers"],
    )
    assert resp1.status_code == 200
    assert resp1.json()["audio_route"] == "earpiece"

    # Switch to wired headset
    resp2 = await client.post(
        f"/sessions/{session['id']}/audio/route",
        json={"audio_route": "headset"},
        headers=helper["headers"],
    )
    assert resp2.status_code == 200
    assert resp2.json()["audio_route"] == "headset"


@pytest.mark.asyncio(loop_scope="session")
async def test_report_audio_degradation(client: AsyncClient) -> None:
    """Client can report network degradation and trigger adaptive quality level adjustment."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    await client.post(
        f"/sessions/{session['id']}/audio/start",
        headers=helper["headers"],
    )

    # Report high packet loss / network degradation
    resp = await client.post(
        f"/sessions/{session['id']}/audio/degradation",
        json={"quality_level": "low", "packet_loss": 12.5},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["audio_quality"] == "low"


@pytest.mark.asyncio(loop_scope="session")
async def test_stop_audio_call(client: AsyncClient) -> None:
    """Participant can stop/leave an active audio call."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    await client.post(
        f"/sessions/{session['id']}/audio/start",
        headers=helper["headers"],
    )

    resp = await client.post(
        f"/sessions/{session['id']}/audio/stop",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["is_in_audio_call"] is False


@pytest.mark.asyncio(loop_scope="session")
async def test_get_audio_status(client: AsyncClient) -> None:
    """Participants can query active voice communication status."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    # Helpee starts audio call with bluetooth
    await client.post(
        f"/sessions/{session['id']}/audio/start",
        json={"is_muted": True, "audio_route": "bluetooth"},
        headers=helpee["headers"],
    )

    # Query status
    resp = await client.get(
        f"/sessions/{session['id']}/audio/status",
        headers=helpee["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_in_audio_call"] is True
    assert data["is_audio_muted"] is True
    assert data["audio_route"] == "bluetooth"
