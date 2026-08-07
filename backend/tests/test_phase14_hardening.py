"""Comprehensive test suite for Phase 14 Performance Optimization, Hardening & Security Auditing.

Covers: WebRTC connection recovery ICE restart state machine, cryptographic key zeroization memory scrub policies,
sliding window RateLimiter 429 enforcement, and complete platform end-to-end multi-phase integration verification.
"""

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from core.rate_limiter import RateLimiter
from tests.test_sessions import _create_session, _register


@pytest.mark.asyncio(loop_scope="session")
async def test_ice_restart_success(client: AsyncClient) -> None:
    """Participant can trigger WebRTC connection recovery ICE restart and receive fresh ufrag/pwd credentials."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/ice-restart",
        json={"reason": "connection_degraded_wifi_switch"},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ice_restart_triggered"] is True
    assert data["ufrag"].startswith("ufrag_")
    assert data["pwd"].startswith("pwd_")


@pytest.mark.asyncio(loop_scope="session")
async def test_security_zeroization_success(client: AsyncClient) -> None:
    """Participant can trigger key zeroization memory scrub to wipe E2EE state and remote control grants."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    # Enable E2EE and verify
    exchange_resp = await client.post(
        f"/sessions/{session['id']}/e2ee/keys/exchange",
        json={
            "identity_key": "ik_123",
            "signed_prekey": "spk_456",
            "ephemeral_key": "ek_789",
        },
        headers=helpee["headers"],
    )
    fingerprint = exchange_resp.json()["fingerprint"]
    await client.post(
        f"/sessions/{session['id']}/e2ee/verify",
        json={
            "safety_number_fingerprint": fingerprint,
            "is_verified_by_user": True,
        },
        headers=helper["headers"],
    )

    # Perform Zeroization
    resp = await client.post(
        f"/sessions/{session['id']}/security/zeroize",
        json={"zeroize_reason": "session_teardown_security_scrub"},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["zeroized"] is True
    assert resp.json()["keys_scrubbed_count"] == 4

    # Verify E2EE state is reset
    status_resp = await client.get(
        f"/sessions/{session['id']}/e2ee/status",
        headers=helper["headers"],
    )
    assert status_resp.json()["is_mitm_verified"] is False
    assert status_resp.json()["fingerprint"] is None


@pytest.mark.asyncio(loop_scope="session")
async def test_rate_limiter_enforcement() -> None:
    """RateLimiter middleware throws 429 Too Many Requests when request threshold is exceeded."""
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    client_ip = "192.168.1.100"

    limiter.check_rate_limit(client_ip)
    limiter.check_rate_limit(client_ip)
    limiter.check_rate_limit(client_ip)

    # 4th request must raise 429
    with pytest.raises(HTTPException) as exc_info:
        limiter.check_rate_limit(client_ip)

    assert exc_info.value.status_code == 429
    assert "rate limit exceeded" in exc_info.value.detail.lower()


@pytest.mark.asyncio(loop_scope="session")
async def test_full_platform_end_to_end_verification(client: AsyncClient) -> None:
    """Comprehensive end-to-end integration test validating all 14 project phases working seamlessly."""
    helper = await _register(client)
    helpee = await _register(client)
    secondary_helper = await _register(client)

    # 1. Auth & Contacts
    contact_resp = await client.post(
        "/contacts/",
        json={"contact_email": helpee["email"]},
        headers=helper["headers"],
    )
    assert contact_resp.status_code == 201

    # 2. Session Create & Join
    session = await _create_session(client, helper["headers"])
    join_resp = await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )
    assert join_resp.status_code == 200

    # 3. WebRTC ICE Config
    ice_resp = await client.get(
        f"/sessions/{session['id']}/ice-servers",
        headers=helper["headers"],
    )
    assert ice_resp.status_code == 200

    # 4. E2EE Key Exchange
    key_resp = await client.post(
        f"/sessions/{session['id']}/e2ee/keys/exchange",
        json={
            "identity_key": "ik_e2e_123",
            "signed_prekey": "spk_e2e_456",
            "ephemeral_key": "ek_e2e_789",
        },
        headers=helpee["headers"],
    )
    assert key_resp.status_code == 200

    # 5. Screen Share & Security Guard
    ss_resp = await client.post(
        f"/sessions/{session['id']}/screen-share/start",
        json={"platform": "android"},
        headers=helpee["headers"],
    )
    assert ss_resp.status_code == 200

    # 6. Voice Call
    voice_resp = await client.post(
        f"/sessions/{session['id']}/audio/start",
        json={"audio_route": "speaker"},
        headers=helper["headers"],
    )
    assert voice_resp.status_code == 200

    # 7. Remote Control Protocol
    rc_grant = await client.post(
        f"/sessions/{session['id']}/remote-control/grant",
        json={"platform": "android_accessibility"},
        headers=helpee["headers"],
    )
    assert rc_grant.status_code == 200

    rc_event = await client.post(
        f"/sessions/{session['id']}/remote-control/input",
        json={"event_type": "tap", "x": 540.0, "y": 960.0},
        headers=helper["headers"],
    )
    assert rc_event.status_code == 200

    # 8. Adaptive Streaming
    adapt_resp = await client.post(
        f"/sessions/{session['id']}/streaming/adapt",
        json={"video_resolution": "720p", "video_fps": 30},
        headers=helper["headers"],
    )
    assert adapt_resp.status_code == 200

    # 9. Session Recording & Audit Trail
    await client.post(
        f"/sessions/{session['id']}/recording/consent",
        json={"consent_granted": True},
        headers=helpee["headers"],
    )
    rec_start = await client.post(
        f"/sessions/{session['id']}/recording/start",
        headers=helper["headers"],
    )
    assert rec_start.status_code == 200

    # 10. Multi-party Assistance
    invite_resp = await client.post(
        f"/sessions/{session['id']}/participants/invite",
        json={
            "email_or_user_id": secondary_helper["email"],
            "role": "secondary_helper",
        },
        headers=helper["headers"],
    )
    assert invite_resp.status_code == 200

    # 11. In-App Chat & Chunked File Transfer
    chat_resp = await client.post(
        f"/sessions/{session['id']}/chat/messages",
        json={"content": "Final E2E test message"},
        headers=helper["headers"],
    )
    assert chat_resp.status_code == 200

    dummy_checksum = "d" * 64
    file_init = await client.post(
        f"/sessions/{session['id']}/files/initiate",
        json={
            "filename": "final_report.doc",
            "file_size_bytes": 1024,
            "checksum_sha256": dummy_checksum,
        },
        headers=helper["headers"],
    )
    assert file_init.status_code == 200

    # 12. ICE Restart & Zeroization (Hardening)
    ice_restart = await client.post(
        f"/sessions/{session['id']}/ice-restart",
        headers=helper["headers"],
    )
    assert ice_restart.status_code == 200

    zeroize = await client.post(
        f"/sessions/{session['id']}/security/zeroize",
        headers=helper["headers"],
    )
    assert zeroize.status_code == 200

    # End Session
    end_resp = await client.post(
        f"/sessions/{session['id']}/end",
        headers=helper["headers"],
    )
    assert end_resp.status_code == 200
    assert end_resp.json()["status"] == "ended"

