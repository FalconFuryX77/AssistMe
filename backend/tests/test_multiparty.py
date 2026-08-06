"""Comprehensive test suite for Phase 10 Multi-party Assistance Sessions & Role Management.

Covers: secondary helper / observer invitations, creator-only RBAC role updates, 403 permission guards,
active speaker layout switching, and multi-party participant listing.
"""

import pytest
from httpx import AsyncClient

from tests.test_sessions import _create_session, _register


@pytest.mark.asyncio(loop_scope="session")
async def test_invite_participant_success(client: AsyncClient) -> None:
    """Session creator can invite a secondary helper to an active session."""
    primary_helper = await _register(client)
    secondary_helper = await _register(client)

    session = await _create_session(client, primary_helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/participants/invite",
        json={
            "email_or_user_id": secondary_helper["user"]["email"],
            "role": "secondary_helper",
        },
        headers=primary_helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == secondary_helper["user"]["id"]
    assert data["role"] == "secondary_helper"


@pytest.mark.asyncio(loop_scope="session")
async def test_invite_participant_role_observer(client: AsyncClient) -> None:
    """Session creator can invite an observer to a session."""
    creator = await _register(client)
    observer = await _register(client)

    session = await _create_session(client, creator["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/participants/invite",
        json={
            "email_or_user_id": observer["user"]["id"],
            "role": "observer",
        },
        headers=creator["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "observer"


@pytest.mark.asyncio(loop_scope="session")
async def test_invite_participant_unauthorized(client: AsyncClient) -> None:
    """Non-creator attempting to invite a participant receives 403 Forbidden."""
    creator = await _register(client)
    other_user = await _register(client)
    invitee = await _register(client)

    session = await _create_session(client, creator["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/participants/invite",
        json={
            "email_or_user_id": invitee["user"]["id"],
            "role": "secondary_helper",
        },
        headers=other_user["headers"],
    )
    assert resp.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_update_participant_role_success(client: AsyncClient) -> None:
    """Session creator can update a participant's role."""
    creator = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, creator["headers"])
    join_resp = await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )
    helpee_participant_id = join_resp.json()["participants"][1]["id"]

    resp = await client.patch(
        f"/sessions/{session['id']}/participants/{helpee_participant_id}/role",
        json={"role": "observer"},
        headers=creator["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "observer"


@pytest.mark.asyncio(loop_scope="session")
async def test_update_participant_role_unauthorized(client: AsyncClient) -> None:
    """Non-creator attempting to update participant role receives 403 Forbidden."""
    creator = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, creator["headers"])
    join_resp = await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )
    creator_participant_id = join_resp.json()["participants"][0]["id"]

    resp = await client.patch(
        f"/sessions/{session['id']}/participants/{creator_participant_id}/role",
        json={"role": "observer"},
        headers=helpee["headers"],
    )
    assert resp.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_set_active_speaker_success(client: AsyncClient) -> None:
    """Participant can signal active speaker change for multi-stream video routing."""
    creator = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, creator["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    resp = await client.post(
        f"/sessions/{session['id']}/active-speaker",
        json={
            "active_speaker_user_id": helpee["user"]["id"],
            "audio_level_db": -12.5,
        },
        headers=creator["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_speaker_user_id"] == helpee["user"]["id"]
    assert data["audio_level_db"] == -12.5


@pytest.mark.asyncio(loop_scope="session")
async def test_list_session_participants(client: AsyncClient) -> None:
    """Participants can query all participants in a multi-party session."""
    creator = await _register(client)
    secondary_helper = await _register(client)

    session = await _create_session(client, creator["headers"])
    await client.post(
        f"/sessions/{session['id']}/participants/invite",
        json={
            "email_or_user_id": secondary_helper["user"]["id"],
            "role": "secondary_helper",
        },
        headers=creator["headers"],
    )

    resp = await client.get(
        f"/sessions/{session['id']}/participants",
        headers=creator["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_participants"] == 2
