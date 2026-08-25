"""Comprehensive test suite for Phase 11 Intelligent Assistance.

Covers: repeated-task learning (occurrence counting), context-aware suggestion
generation, preferred-mode memory, cold-start fallback, and authorization.
"""

import pytest
from httpx import AsyncClient

from tests.test_sessions import _create_session, _register


@pytest.mark.asyncio(loop_scope="session")
async def test_record_task_learns_pattern(client: AsyncClient) -> None:
    """Recording a task creates a pattern with occurrence_count == 1."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/assistance/tasks",
        json={
            "foreground_app": "com.android.settings",
            "platform": "android",
            "action": "remote_control",
        },
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["occurrence_count"] == 1
    assert data["action"] == "remote_control"


@pytest.mark.asyncio(loop_scope="session")
async def test_repeated_task_increments_count(client: AsyncClient) -> None:
    """Recording the same task twice increments occurrence_count."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])
    payload = {
        "foreground_app": "com.android.settings",
        "platform": "android",
        "action": "remote_control",
    }

    await client.post(
        f"/sessions/{session['id']}/assistance/tasks",
        json=payload,
        headers=helper["headers"],
    )
    resp = await client.post(
        f"/sessions/{session['id']}/assistance/tasks",
        json=payload,
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["occurrence_count"] == 2


@pytest.mark.asyncio(loop_scope="session")
async def test_invalid_action_rejected(client: AsyncClient) -> None:
    """Invalid action returns 422."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/assistance/tasks",
        json={"action": "teleport"},
        headers=helper["headers"],
    )
    assert resp.status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_cold_start_suggestion(client: AsyncClient) -> None:
    """With no learned patterns, a context_help suggestion is generated."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.get(
        f"/sessions/{session['id']}/assistance/suggestions",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_suggestions"] == 1
    assert data["suggestions"][0]["suggestion_type"] == "context_help"


@pytest.mark.asyncio(loop_scope="session")
async def test_repeated_task_suggestion(client: AsyncClient) -> None:
    """Repeated task patterns produce a repeated_task suggestion."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])
    payload = {
        "foreground_app": "com.android.settings",
        "platform": "android",
        "action": "remote_control",
    }

    # Record the task twice so it counts as repeated.
    for _ in range(2):
        await client.post(
            f"/sessions/{session['id']}/assistance/tasks",
            json=payload,
            headers=helper["headers"],
        )

    resp = await client.get(
        f"/sessions/{session['id']}/assistance/suggestions",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    types = {s["suggestion_type"] for s in data["suggestions"]}
    assert "repeated_task" in types
    assert any(s["confidence"] > 0 for s in data["suggestions"])


@pytest.mark.asyncio(loop_scope="session")
async def test_preferred_mode_reminder(client: AsyncClient) -> None:
    """Setting a preferred mode produces a preferred_mode suggestion."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    # Set preferred mode
    await client.put(
        "/users/me/assistance/preferred-mode",
        json={"mode": "tap"},
        headers=helper["headers"],
    )

    resp = await client.get(
        f"/sessions/{session['id']}/assistance/suggestions",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert any(
        s["suggestion_type"] == "preferred_mode" for s in data["suggestions"]
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_preferred_mode_set_and_get(client: AsyncClient) -> None:
    """Preferred mode can be set and retrieved."""
    helper = await _register(client)

    resp = await client.put(
        "/users/me/assistance/preferred-mode",
        json={"mode": "pointer"},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["mode"] == "pointer"

    resp = await client.get(
        "/users/me/assistance/preferred-mode",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["mode"] == "pointer"


@pytest.mark.asyncio(loop_scope="session")
async def test_preferred_mode_default_none(client: AsyncClient) -> None:
    """Preferred mode is null before being set."""
    helper = await _register(client)

    resp = await client.get(
        "/users/me/assistance/preferred-mode",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json() is None


@pytest.mark.asyncio(loop_scope="session")
async def test_preferred_mode_update(client: AsyncClient) -> None:
    """Preferred mode can be updated in place."""
    helper = await _register(client)

    await client.put(
        "/users/me/assistance/preferred-mode",
        json={"mode": "voice"},
        headers=helper["headers"],
    )
    resp = await client.put(
        "/users/me/assistance/preferred-mode",
        json={"mode": "drawing"},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["mode"] == "drawing"


@pytest.mark.asyncio(loop_scope="session")
async def test_list_task_patterns(client: AsyncClient) -> None:
    """User can list their learned task patterns."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])
    await client.post(
        f"/sessions/{session['id']}/assistance/tasks",
        json={"foreground_app": "com.android.settings", "action": "voice"},
        headers=helper["headers"],
    )

    resp = await client.get(
        "/users/me/assistance/task-patterns",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_patterns"] >= 1
    assert data["patterns"][0]["action"] == "voice"


@pytest.mark.asyncio(loop_scope="session")
async def test_suggestions_non_participant_forbidden(client: AsyncClient) -> None:
    """Non-participants cannot request suggestions."""
    helper = await _register(client)
    outsider = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.get(
        f"/sessions/{session['id']}/assistance/suggestions",
        headers=outsider["headers"],
    )
    assert resp.status_code == 403