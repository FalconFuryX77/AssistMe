"""Comprehensive test suite for Phase 9 Adaptive Policy Engine.

Covers: risk classification (low/medium/high), capability negotiation,
assistance mode selection, consent verification, protected apps / FLAG_SECURE
restrictions, permission transitions, and state transitions.
"""

import hashlib

import pytest
from httpx import AsyncClient

from tests.test_sessions import _create_session, _register


def _consent_token(session_id: str) -> str:
    return hashlib.sha256(f"assistme-consent-{session_id}".encode()).hexdigest()[:32]


async def _report_context(client, session_id, headers, **overrides):
    payload = {
        "platform": "android",
        "accessibility_enabled": True,
        "accessibility_gesture_capable": True,
    }
    payload.update(overrides)
    await client.post(
        f"/sessions/{session_id}/context/report",
        json=payload,
        headers=headers,
    )


@pytest.mark.asyncio(loop_scope="session")
async def test_evaluate_low_risk_full_capabilities(client: AsyncClient) -> None:
    """Low-risk context grants requested full capabilities."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])
    await _report_context(
        client, session["id"], helper["headers"],
        foreground_app="com.android.settings",
        foreground_app_category="system",
    )

    resp = await client.post(
        f"/sessions/{session['id']}/policy/evaluate",
        json={
            "requested_capabilities": ["tap", "drawing", "pointer", "voice", "drag"],
        },
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["risk_level"] == "low"
    assert "tap" in data["negotiated_capabilities"]
    assert data["assistance_mode"] == "tap"


@pytest.mark.asyncio(loop_scope="session")
async def test_evaluate_high_risk_restricted(client: AsyncClient) -> None:
    """Sensitive app / FLAG_SECURE context restricts to view-only."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])
    await _report_context(
        client, session["id"], helper["headers"],
        foreground_app="com.example.banking",
        foreground_app_category="banking",
        is_sensitive_app=True,
        is_flag_secure_active=True,
    )

    resp = await client.post(
        f"/sessions/{session['id']}/policy/evaluate",
        json={"requested_capabilities": ["tap", "drawing", "pointer", "voice"]},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["risk_level"] == "high"
    assert data["assistance_mode"] == "restricted"
    assert data["negotiated_capabilities"] == []
    assert any("sensitive" in r.lower() for r in data["risk_reasons"])


@pytest.mark.asyncio(loop_scope="session")
async def test_evaluate_medium_risk_no_tap(client: AsyncClient) -> None:
    """Medium-risk context disallows tap but keeps pointer/drawing."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])
    # Protected app category (medium) without FLAG_SECURE.
    await _report_context(
        client, session["id"], helper["headers"],
        foreground_app="com.example.shopping",
        foreground_app_category="ecommerce",
    )

    resp = await client.post(
        f"/sessions/{session['id']}/policy/evaluate",
        json={"requested_capabilities": ["tap", "drawing", "pointer", "voice"]},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["risk_level"] == "medium"
    assert "tap" not in data["negotiated_capabilities"]
    assert "pointer" in data["negotiated_capabilities"]
    assert data["assistance_mode"] == "drawing"


@pytest.mark.asyncio(loop_scope="session")
async def test_medium_risk_without_accessibility_voice_only(client: AsyncClient) -> None:
    """Medium risk without accessibility enabled drops pointer/drawing → voice."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])
    await _report_context(
        client, session["id"], helper["headers"],
        foreground_app="com.example.shopping",
        foreground_app_category="ecommerce",
        accessibility_enabled=False,
        accessibility_gesture_capable=False,
    )

    resp = await client.post(
        f"/sessions/{session['id']}/policy/evaluate",
        json={"requested_capabilities": ["tap", "drawing", "pointer", "voice"]},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["assistance_mode"] == "voice"
    assert data["negotiated_capabilities"] == ["voice"]


@pytest.mark.asyncio(loop_scope="session")
async def test_negotiate_capabilities_constrained_by_risk(client: AsyncClient) -> None:
    """Capability negotiation endpoint constrains by context."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])
    await _report_context(
        client, session["id"], helper["headers"],
        foreground_app="com.example.banking",
        foreground_app_category="banking",
        is_sensitive_app=True,
    )

    resp = await client.post(
        f"/sessions/{session['id']}/policy/capabilities",
        json={"capabilities": ["tap", "pointer", "voice"]},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["risk_level"] == "high"
    assert data["negotiated_capabilities"] == []


@pytest.mark.asyncio(loop_scope="session")
async def test_consent_verification_success(client: AsyncClient) -> None:
    """Valid consent token marks consent verified."""
    helper = await _register(client)
    helpee = await _register(client)
    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    resp = await client.post(
        f"/sessions/{session['id']}/policy/consent",
        json={
            "consent_token": _consent_token(session["id"]),
            "capabilities": ["tap", "pointer", "voice"],
        },
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["consent_verified"] is True
    assert data["consent_granted_at"] is not None


@pytest.mark.asyncio(loop_scope="session")
async def test_consent_verification_invalid_token(client: AsyncClient) -> None:
    """Invalid consent token returns 403."""
    helper = await _register(client)
    helpee = await _register(client)
    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    resp = await client.post(
        f"/sessions/{session['id']}/policy/consent",
        json={"consent_token": "invalid-token", "capabilities": ["tap"]},
        headers=helper["headers"],
    )
    assert resp.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_policy_status_default(client: AsyncClient) -> None:
    """Status returns a conservative default before first evaluation."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.get(
        f"/sessions/{session['id']}/policy/status",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["assistance_mode"] == "voice"
    assert data["consent_verified"] is False


@pytest.mark.asyncio(loop_scope="session")
async def test_policy_status_after_evaluation(client: AsyncClient) -> None:
    """Status reflects the last evaluation."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])
    await _report_context(
        client, session["id"], helper["headers"],
        foreground_app="com.example.banking",
        foreground_app_category="banking",
        is_sensitive_app=True,
    )
    await client.post(
        f"/sessions/{session['id']}/policy/evaluate",
        json={"requested_capabilities": ["tap"]},
        headers=helper["headers"],
    )

    resp = await client.get(
        f"/sessions/{session['id']}/policy/status",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["assistance_mode"] == "restricted"


@pytest.mark.asyncio(loop_scope="session")
async def test_policy_non_participant_forbidden(client: AsyncClient) -> None:
    """Non-participants cannot evaluate policy."""
    helper = await _register(client)
    outsider = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/policy/evaluate",
        json={"requested_capabilities": ["tap"]},
        headers=outsider["headers"],
    )
    assert resp.status_code == 403
