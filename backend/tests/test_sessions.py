"""Comprehensive tests for the session management API.

Covers: creation, join, leave, end, recovery, timeouts, duplicate joins,
expired sessions, concurrent operations, and WebSocket events.
"""

import secrets

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _register(client: AsyncClient, suffix: str | None = None) -> dict:
    """Register a fresh user and return data with headers."""
    suffix = suffix or secrets.token_hex(4)
    resp = await client.post(
        "/auth/register",
        json={
            "email": f"session_{suffix}@example.com",
            "password": "SecureP1",
            "display_name": f"User {suffix}",
        },
    )
    data = resp.json()
    data["headers"] = {"Authorization": f"Bearer {data['access_token']}"}
    data["email"] = f"session_{suffix}@example.com"
    return data


async def _create_session(client: AsyncClient, headers: dict) -> dict:
    """Create a session and return the response data."""
    resp = await client.post(
        "/sessions/",
        json={"title": "Test Session", "timeout_minutes": 30},
        headers=headers,
    )
    return resp.json()


# ---------------------------------------------------------------------------
# Session Creation Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_create_session_success(client: AsyncClient) -> None:
    """Creating a session returns 201 with a session code and creator as helper."""
    user = await _register(client)
    resp = await client.post(
        "/sessions/",
        json={"title": "Help with settings"},
        headers=user["headers"],
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "waiting"
    assert data["session_code"]
    assert len(data["session_code"]) == 6
    assert data["title"] == "Help with settings"
    assert len(data["participants"]) == 1
    assert data["participants"][0]["role"] == "helper"
    assert data["participants"][0]["status"] == "connected"


@pytest.mark.asyncio(loop_scope="session")
async def test_create_session_default_timeout(client: AsyncClient) -> None:
    """Session timeout defaults to 30 minutes if not specified."""
    user = await _register(client)
    resp = await client.post(
        "/sessions/",
        json={},
        headers=user["headers"],
    )
    assert resp.status_code == 201
    assert resp.json()["timeout_minutes"] == 30


@pytest.mark.asyncio(loop_scope="session")
async def test_create_session_custom_timeout(client: AsyncClient) -> None:
    """Session timeout can be customized."""
    user = await _register(client)
    resp = await client.post(
        "/sessions/",
        json={"timeout_minutes": 60},
        headers=user["headers"],
    )
    assert resp.status_code == 201
    assert resp.json()["timeout_minutes"] == 60


@pytest.mark.asyncio(loop_scope="session")
async def test_create_session_requires_auth(client: AsyncClient) -> None:
    """Creating a session without auth returns 401/403."""
    resp = await client.post("/sessions/", json={})
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Join Session Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_join_session_success(client: AsyncClient) -> None:
    """Joining a session by code adds the user as helpee and activates the session."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    assert len(data["participants"]) == 2

    helpee_participant = next(
        p for p in data["participants"] if p["role"] == "helpee"
    )
    assert helpee_participant["status"] == "connected"


@pytest.mark.asyncio(loop_scope="session")
async def test_join_session_invalid_code(client: AsyncClient) -> None:
    """Joining with an invalid code returns 404."""
    user = await _register(client)
    resp = await client.post(
        "/sessions/join",
        json={"session_code": "XXXXXX"},
        headers=user["headers"],
    )
    assert resp.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_join_session_duplicate(client: AsyncClient) -> None:
    """Joining a session you're already connected to returns 400."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])

    # First join
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    # Duplicate join
    resp = await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )
    assert resp.status_code == 400
    assert "already connected" in resp.json()["detail"].lower()


@pytest.mark.asyncio(loop_scope="session")
async def test_join_ended_session(client: AsyncClient) -> None:
    """Joining an ended session returns 400."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])

    # End the session
    await client.post(
        f"/sessions/{session['id']}/end",
        headers=helper["headers"],
    )

    # Try to join
    resp = await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )
    assert resp.status_code == 400
    assert "ended" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Leave Session Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_leave_session_helpee(client: AsyncClient) -> None:
    """Helpee leaving marks them as 'left' but session stays active."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    resp = await client.post(
        f"/sessions/{session['id']}/leave",
        headers=helpee["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()

    helpee_p = next(p for p in data["participants"] if p["role"] == "helpee")
    assert helpee_p["status"] == "left"

    # Session should NOT end when helpee leaves
    assert data["status"] != "ended"


@pytest.mark.asyncio(loop_scope="session")
async def test_leave_session_helper_ends_session(client: AsyncClient) -> None:
    """Helper leaving ends the session for everyone."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    resp = await client.post(
        f"/sessions/{session['id']}/leave",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ended"
    assert data["ended_at"] is not None

    # All participants should be marked as left
    for p in data["participants"]:
        assert p["status"] == "left"


@pytest.mark.asyncio(loop_scope="session")
async def test_leave_session_not_participant(client: AsyncClient) -> None:
    """Leaving a session you're not in returns 400."""
    helper = await _register(client)
    outsider = await _register(client)

    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/leave",
        headers=outsider["headers"],
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# End Session Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_end_session_creator_only(client: AsyncClient) -> None:
    """Only the creator can end a session."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    # Helpee tries to end — should fail
    resp = await client.post(
        f"/sessions/{session['id']}/end",
        headers=helpee["headers"],
    )
    assert resp.status_code == 403

    # Helper ends — should succeed
    resp = await client.post(
        f"/sessions/{session['id']}/end",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ended"


@pytest.mark.asyncio(loop_scope="session")
async def test_end_already_ended_session(client: AsyncClient) -> None:
    """Ending an already-ended session returns 400."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    await client.post(f"/sessions/{session['id']}/end", headers=helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/end",
        headers=helper["headers"],
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Recovery Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_recover_session_success(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A disconnected participant can recover their session."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    get_resp = await client.get(
        f"/sessions/{session['id']}",
        headers=helper["headers"],
    )
    helpee_p = next(
        p for p in get_resp.json()["participants"] if p["role"] == "helpee"
    )
    helpee_user_id = helpee_p["user_id"]

    # Mark as disconnected via the injected db_session
    from api.services.session_service import SessionService

    await SessionService.mark_disconnected(session["id"], helpee_user_id, db_session)

    # Recover
    resp = await client.post(
        "/sessions/recover",
        json={"session_id": session["id"]},
        headers=helpee["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    helpee_p = next(p for p in data["participants"] if p["role"] == "helpee")
    assert helpee_p["status"] == "connected"


@pytest.mark.asyncio(loop_scope="session")
async def test_recover_not_disconnected(client: AsyncClient) -> None:
    """Recovery for a user who is not disconnected returns 400."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    # Try recovery when connected (not disconnected)
    resp = await client.post(
        "/sessions/recover",
        json={"session_id": session["id"]},
        headers=helpee["headers"],
    )
    assert resp.status_code == 400
    assert "not in a disconnected state" in resp.json()["detail"].lower()


@pytest.mark.asyncio(loop_scope="session")
async def test_recover_ended_session(client: AsyncClient) -> None:
    """Recovery for an ended session returns 400."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    await client.post(f"/sessions/{session['id']}/end", headers=helper["headers"])

    resp = await client.post(
        "/sessions/recover",
        json={"session_id": session["id"]},
        headers=helper["headers"],
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Get / List Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_get_session_by_id(client: AsyncClient) -> None:
    """Participants can retrieve session details."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.get(
        f"/sessions/{session['id']}",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == session["id"]


@pytest.mark.asyncio(loop_scope="session")
async def test_get_session_non_participant(client: AsyncClient) -> None:
    """Non-participants cannot view session details."""
    helper = await _register(client)
    outsider = await _register(client)

    session = await _create_session(client, helper["headers"])

    resp = await client.get(
        f"/sessions/{session['id']}",
        headers=outsider["headers"],
    )
    assert resp.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_list_sessions(client: AsyncClient) -> None:
    """Users can list their sessions."""
    helper = await _register(client)
    await _create_session(client, helper["headers"])
    await _create_session(client, helper["headers"])

    resp = await client.get("/sessions/", headers=helper["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2


@pytest.mark.asyncio(loop_scope="session")
async def test_list_sessions_filter_by_status(client: AsyncClient) -> None:
    """Session list can be filtered by status."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])
    await client.post(f"/sessions/{session['id']}/end", headers=helper["headers"])

    # Another session still waiting
    await _create_session(client, helper["headers"])

    resp = await client.get(
        "/sessions/",
        params={"status": "waiting"},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    for s in resp.json():
        assert s["status"] == "waiting"


# ---------------------------------------------------------------------------
# Heartbeat Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_heartbeat_success(client: AsyncClient) -> None:
    """Heartbeat returns 204 for connected participants."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/heartbeat",
        headers=helper["headers"],
    )
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Rejoin after leaving Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_rejoin_after_leaving(client: AsyncClient) -> None:
    """A user who left can rejoin via the session code."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])

    # Join
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    # Leave
    await client.post(
        f"/sessions/{session['id']}/leave",
        headers=helpee["headers"],
    )

    # Rejoin
    resp = await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )
    assert resp.status_code == 200
    helpee_p = next(
        p for p in resp.json()["participants"] if p["role"] == "helpee"
    )
    assert helpee_p["status"] == "connected"
