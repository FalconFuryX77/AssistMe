"""Comprehensive test suite for Phase 9 Session Recording & Audit Trails.

Covers: recording consent workflows, start recording enforcement (403 Forbidden without consent),
stop recording & file metadata storage, recording status query, and privacy compliance audit trail logging.
"""

import pytest
from httpx import AsyncClient

from tests.test_sessions import _create_session, _register


@pytest.mark.asyncio(loop_scope="session")
async def test_update_recording_consent_success(client: AsyncClient) -> None:
    """Participant can grant recording consent with a specified scope."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    resp = await client.post(
        f"/sessions/{session['id']}/recording/consent",
        json={"consent_granted": True, "recording_scope": "screen_and_audio"},
        headers=helpee["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["consent_granted"] is True
    assert data["recording_scope"] == "screen_and_audio"


@pytest.mark.asyncio(loop_scope="session")
async def test_update_recording_consent_invalid_scope(client: AsyncClient) -> None:
    """Invalid recording_scope string returns 422 validation error."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/recording/consent",
        json={"consent_granted": True, "recording_scope": "full_hd_vr"},
        headers=helper["headers"],
    )
    assert resp.status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_start_recording_without_consent_fails(client: AsyncClient) -> None:
    """Attempting to start recording before consent is granted returns 403 Forbidden."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    # Attempt start without consent
    resp = await client.post(
        f"/sessions/{session['id']}/recording/start",
        json={"storage_provider": "local_encrypted"},
        headers=helper["headers"],
    )
    assert resp.status_code == 403
    assert "consent" in resp.json()["detail"].lower()


@pytest.mark.asyncio(loop_scope="session")
async def test_start_recording_with_consent(client: AsyncClient) -> None:
    """Helper can start recording after consent is granted by helpee."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    # Grant consent
    await client.post(
        f"/sessions/{session['id']}/recording/consent",
        json={"consent_granted": True, "recording_scope": "screen_only"},
        headers=helpee["headers"],
    )

    # Start recording
    resp = await client.post(
        f"/sessions/{session['id']}/recording/start",
        json={"storage_provider": "local_encrypted"},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["is_recording"] is True


@pytest.mark.asyncio(loop_scope="session")
async def test_stop_recording_success(client: AsyncClient) -> None:
    """Helper can stop recording and save file URL, size, and duration metadata."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )
    await client.post(
        f"/sessions/{session['id']}/recording/consent",
        json={"consent_granted": True},
        headers=helpee["headers"],
    )
    await client.post(
        f"/sessions/{session['id']}/recording/start",
        headers=helper["headers"],
    )

    # Stop recording
    resp = await client.post(
        f"/sessions/{session['id']}/recording/stop",
        json={
            "file_url": "https://storage.assistme.internal/recordings/rec_123.mp4",
            "file_size_bytes": 15420000,
            "duration_seconds": 180,
        },
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_recording"] is False
    assert data["recording_url"] == "https://storage.assistme.internal/recordings/rec_123.mp4"
    assert data["file_size_bytes"] == 15420000
    assert data["duration_seconds"] == 180


@pytest.mark.asyncio(loop_scope="session")
async def test_get_recording_status(client: AsyncClient) -> None:
    """Participants can query active recording status and metadata."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.get(
        f"/sessions/{session['id']}/recording/status",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["is_recording"] is False


@pytest.mark.asyncio(loop_scope="session")
async def test_get_audit_trail(client: AsyncClient) -> None:
    """Participants can query structured privacy compliance audit logs for a session."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )
    await client.post(
        f"/sessions/{session['id']}/recording/consent",
        json={"consent_granted": True},
        headers=helpee["headers"],
    )

    # Fetch audit trail
    resp = await client.get(
        f"/sessions/{session['id']}/audit-trail",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_events"] >= 1
    events = data["events"]
    assert any(e["event_type"] == "recording_consent_updated" for e in events)
