"""Comprehensive test suite for Phase 8 End-to-End Encryption (E2EE) & Signal Protocol WebRTC Security.

Covers: Signal Double Ratchet key exchange, SHA-256 safety number fingerprint derivation,
ephemeral key rotation, SAS fingerprint verification, Man-In-The-Middle (MITM) detection, and security status queries.
"""

import pytest
from httpx import AsyncClient

from tests.test_sessions import _create_session, _register


@pytest.mark.asyncio(loop_scope="session")
async def test_e2ee_key_exchange_success(client: AsyncClient) -> None:
    """Participants can perform E2EE key exchange for WebRTC Insertable Streams."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    resp = await client.post(
        f"/sessions/{session['id']}/e2ee/keys/exchange",
        json={
            "identity_key": "pub_identity_key_abc123",
            "signed_prekey": "pub_signed_prekey_def456",
            "ephemeral_key": "pub_ephemeral_key_ghi789",
            "algorithm": "Signal_DoubleRatchet_AES256_GCM",
        },
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["e2ee_enabled"] is True
    assert data["key_exchange_complete"] is True
    assert data["fingerprint"] is not None
    assert len(data["fingerprint"]) == 64


@pytest.mark.asyncio(loop_scope="session")
async def test_e2ee_key_exchange_invalid_algorithm(client: AsyncClient) -> None:
    """Invalid encryption algorithm string returns 422 validation error."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/e2ee/keys/exchange",
        json={
            "identity_key": "key1",
            "signed_prekey": "key2",
            "ephemeral_key": "key3",
            "algorithm": "DES_56_WEAK",
        },
        headers=helper["headers"],
    )
    assert resp.status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_e2ee_key_rotation_success(client: AsyncClient) -> None:
    """Participants can perform Double Ratchet ephemeral key rotation for forward secrecy."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    # Key exchange first
    await client.post(
        f"/sessions/{session['id']}/e2ee/keys/exchange",
        json={
            "identity_key": "key1",
            "signed_prekey": "key2",
            "ephemeral_key": "key3",
        },
        headers=helper["headers"],
    )

    # Key rotation
    resp = await client.post(
        f"/sessions/{session['id']}/e2ee/keys/rotate",
        json={"new_ephemeral_key": "new_ephemeral_key_999", "ratchet_counter": 1},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["key_exchange_complete"] is True


@pytest.mark.asyncio(loop_scope="session")
async def test_e2ee_key_rotation_before_exchange(client: AsyncClient) -> None:
    """Attempting key rotation before completing key exchange returns 400 Bad Request."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/e2ee/keys/rotate",
        json={"new_ephemeral_key": "new_ephemeral_key_999", "ratchet_counter": 1},
        headers=helper["headers"],
    )
    assert resp.status_code == 400


@pytest.mark.asyncio(loop_scope="session")
async def test_e2ee_verify_fingerprint_success(client: AsyncClient) -> None:
    """Participants can verify SAS safety number fingerprint to confirm clean channel."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    exchange_resp = await client.post(
        f"/sessions/{session['id']}/e2ee/keys/exchange",
        json={
            "identity_key": "identity_secure_val",
            "signed_prekey": "prekey_secure_val",
            "ephemeral_key": "eph_val",
        },
        headers=helper["headers"],
    )
    fingerprint = exchange_resp.json()["fingerprint"]

    # Verify matching fingerprint
    resp = await client.post(
        f"/sessions/{session['id']}/e2ee/verify",
        json={
            "safety_number_fingerprint": fingerprint,
            "is_verified_by_user": True,
        },
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["is_mitm_verified"] is True


@pytest.mark.asyncio(loop_scope="session")
async def test_e2ee_verify_fingerprint_mitm_mismatch_detected(client: AsyncClient) -> None:
    """Mismatched safety number fingerprint returns 400 error, detecting MITM tampering."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    await client.post(
        f"/sessions/{session['id']}/e2ee/keys/exchange",
        json={
            "identity_key": "identity_secure_val",
            "signed_prekey": "prekey_secure_val",
            "ephemeral_key": "eph_val",
        },
        headers=helper["headers"],
    )

    # Attempt verification with bogus fingerprint (MITM scenario)
    bogus_fingerprint = "f" * 64
    resp = await client.post(
        f"/sessions/{session['id']}/e2ee/verify",
        json={
            "safety_number_fingerprint": bogus_fingerprint,
            "is_verified_by_user": True,
        },
        headers=helper["headers"],
    )
    assert resp.status_code == 400
    assert "mismatch" in resp.json()["detail"].lower()


@pytest.mark.asyncio(loop_scope="session")
async def test_get_e2ee_status(client: AsyncClient) -> None:
    """Participants can query active E2EE security status and fingerprint."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.get(
        f"/sessions/{session['id']}/e2ee/status",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["e2ee_enabled"] is True
    assert data["key_exchange_complete"] is False
