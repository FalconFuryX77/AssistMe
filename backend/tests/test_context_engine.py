"""Comprehensive test suite for Phase 8 Context Engine.

Covers: platform detection, foreground app reporting, accessibility state,
sensitive-app classification, permission tracking, screen sharing / security
state, session-state enrichment, and listing snapshots across participants.
"""

import pytest
from httpx import AsyncClient

from tests.test_sessions import _create_session, _register


def _context_payload(**overrides):
    payload = {
        "platform": "android",
        "os_version": "14",
        "device_model": "Pixel 8",
        "screen_width": 1080,
        "screen_height": 1920,
        "screen_density": 2.625,
        "foreground_app": "com.android.settings",
        "foreground_app_category": "system",
        "accessibility_enabled": True,
        "accessibility_gesture_capable": True,
        "screen_share_permission": True,
        "microphone_permission": True,
        "remote_control_permission": True,
        "is_screen_sharing": True,
        "network_type": "wifi",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio(loop_scope="session")
async def test_report_context_success(client: AsyncClient) -> None:
    """Participant can report a full context snapshot."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/context/report",
        json=_context_payload(),
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["platform"] == "android"
    assert data["foreground_app"] == "com.android.settings"
    assert data["accessibility_enabled"] is True
    assert data["is_screen_sharing"] is True
    assert data["network_type"] == "wifi"
    assert data["session_status"] == "waiting"


@pytest.mark.asyncio(loop_scope="session")
async def test_report_context_partial_update(client: AsyncClient) -> None:
    """A partial report updates only the provided fields (upsert)."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    await client.post(
        f"/sessions/{session['id']}/context/report",
        json=_context_payload(),
        headers=helper["headers"],
    )
    resp = await client.post(
        f"/sessions/{session['id']}/context/report",
        json={"platform": "ios", "os_version": "17"},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    # Updated fields
    assert data["platform"] == "ios"
    assert data["os_version"] == "17"
    # Previously reported fields are preserved
    assert data["device_model"] == "Pixel 8"
    assert data["accessibility_enabled"] is True


@pytest.mark.asyncio(loop_scope="session")
async def test_sensitive_app_detected(client: AsyncClient) -> None:
    """Sensitive app categories are flagged to block control/annotation."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/context/report",
        json={
            "platform": "android",
            "foreground_app": "com.example.banking",
            "foreground_app_category": "banking",
        },
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["is_sensitive_app"] is True


@pytest.mark.asyncio(loop_scope="session")
async def test_non_sensitive_app_not_flagged(client: AsyncClient) -> None:
    """Non-sensitive apps are not flagged."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/context/report",
        json={
            "platform": "android",
            "foreground_app": "com.example.calculator",
            "foreground_app_category": "productivity",
        },
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["is_sensitive_app"] is False


@pytest.mark.asyncio(loop_scope="session")
async def test_invalid_platform_rejected(client: AsyncClient) -> None:
    """Invalid platform value returns 422."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/context/report",
        json={"platform": "blackberry"},
        headers=helper["headers"],
    )
    assert resp.status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_get_my_context_requires_report(client: AsyncClient) -> None:
    """Getting context before any report returns 404."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.get(
        f"/sessions/{session['id']}/context/me",
        headers=helper["headers"],
    )
    assert resp.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_get_my_context_after_report(client: AsyncClient) -> None:
    """Context can be retrieved after reporting."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    await client.post(
        f"/sessions/{session['id']}/context/report",
        json=_context_payload(),
        headers=helper["headers"],
    )
    resp = await client.get(
        f"/sessions/{session['id']}/context/me",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["platform"] == "android"


@pytest.mark.asyncio(loop_scope="session")
async def test_list_context_multiple_participants(client: AsyncClient) -> None:
    """Context snapshots are listed for all session participants."""
    helper = await _register(client)
    helpee = await _register(client)
    session = await _create_session(client, helper["headers"])

    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    await client.post(
        f"/sessions/{session['id']}/context/report",
        json=_context_payload(foreground_app="com.android.settings"),
        headers=helper["headers"],
    )
    await client.post(
        f"/sessions/{session['id']}/context/report",
        json=_context_payload(platform="ios", foreground_app="com.apple.settings"),
        headers=helpee["headers"],
    )

    resp = await client.get(
        f"/sessions/{session['id']}/context/",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_snapshots"] == 2
    platforms = {s["platform"] for s in data["snapshots"]}
    assert platforms == {"android", "ios"}


@pytest.mark.asyncio(loop_scope="session")
async def test_context_non_participant_forbidden(client: AsyncClient) -> None:
    """Non-participants cannot report or view context."""
    helper = await _register(client)
    outsider = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/context/report",
        json=_context_payload(),
        headers=outsider["headers"],
    )
    assert resp.status_code == 403
