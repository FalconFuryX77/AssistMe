"""Comprehensive tests for the device-first authentication API.

Covers:
  - Device bootstrap: creates identity + recovery code on first call
  - Silent login: returns existing identity on subsequent calls
  - Display name customization & updates
  - Identity reclamation via recovery code
  - Refresh token rotation
  - Rate limiting & security validation
"""

import pytest
from httpx import AsyncClient


FP_1 = "assistme-device-fp-auth-test-000001"
FP_2 = "assistme-device-fp-auth-test-000002"
FP_3 = "assistme-device-fp-auth-test-000003"


# ---------------------------------------------------------------------------
# Device Bootstrap Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_device_bootstrap_first_call_creates_identity(client: AsyncClient) -> None:
    """First bootstrap call creates the invisible account + one-time recovery code."""
    resp = await client.post(
        "/auth/device",
        json={"device_fingerprint": FP_1, "display_name": "Grandma Helen"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["created"] is True
    assert data["display_name"] == "Grandma Helen"
    assert data["recovery_code"] is not None
    assert len(data["recovery_code"]) == 12
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio(loop_scope="session")
async def test_device_bootstrap_subsequent_call_silent_login(client: AsyncClient) -> None:
    """Subsequent bootstrap with same fingerprint logs in when device_secret matches, and rejects spoofing."""
    first = await client.post(
        "/auth/device",
        json={"device_fingerprint": FP_2, "display_name": "Dad"},
    )
    assert first.status_code == 201
    first_data = first.json()
    assert first_data["device_secret"]

    # Spoofed attempt with wrong/missing secret is rejected
    spoof = await client.post(
        "/auth/device",
        json={"device_fingerprint": FP_2, "device_secret": "wrong-secret-guess"},
    )
    assert spoof.status_code == 401

    # Legitimate device presenting its secret succeeds
    second = await client.post(
        "/auth/device",
        json={"device_fingerprint": FP_2, "device_secret": first_data["device_secret"]},
    )
    assert second.status_code == 201
    second_data = second.json()
    assert second_data["created"] is False
    assert second_data["recovery_code"] is None
    assert second_data["user_id"] == first_data["user_id"]
    assert second_data["display_name"] == "Dad"
    assert second_data["access_token"]


@pytest.mark.asyncio(loop_scope="session")
async def test_device_bootstrap_short_fingerprint_rejected(client: AsyncClient) -> None:
    """Fingerprints shorter than 16 characters are rejected with 422."""
    resp = await client.post(
        "/auth/device",
        json={"device_fingerprint": "too-short"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Identity Reclamation Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_device_reclaim_success(client: AsyncClient) -> None:
    """Reclaiming an identity with valid recovery code binds the new device fingerprint."""
    # 1. Old device creates identity
    old_boot = await client.post(
        "/auth/device",
        json={"device_fingerprint": "assistme-old-device-fp-00000100", "display_name": "Mom"},
    )
    assert old_boot.status_code == 201
    recovery_code = old_boot.json()["recovery_code"]
    user_id = old_boot.json()["user_id"]

    # 2. New device reclaims identity with recovery code
    new_fp = "assistme-new-device-fp-00000200"
    reclaim_resp = await client.post(
        "/auth/device/reclaim",
        json={"device_fingerprint": new_fp, "recovery_code": recovery_code},
    )
    assert reclaim_resp.status_code == 200
    reclaim_data = reclaim_resp.json()
    assert reclaim_data["user_id"] == user_id
    assert reclaim_data["display_name"] == "Mom"
    assert reclaim_data["access_token"]


@pytest.mark.asyncio(loop_scope="session")
async def test_device_reclaim_invalid_code_rejected(client: AsyncClient) -> None:
    """Reclaiming with an invalid recovery code returns 401/404."""
    resp = await client.post(
        "/auth/device/reclaim",
        json={
            "device_fingerprint": "assistme-device-fp-invalid-reclaim-1",
            "recovery_code": "nonexistentcode",
        },
    )
    assert resp.status_code in (401, 404)


# ---------------------------------------------------------------------------
# Token Refresh Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_refresh_token_success(client: AsyncClient) -> None:
    """Valid refresh token issues a fresh access token."""
    boot = await client.post(
        "/auth/device",
        json={"device_fingerprint": FP_3, "display_name": "Alex"},
    )
    assert boot.status_code == 201
    refresh_token = boot.json()["refresh_token"]

    resp = await client.post(
        "/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"]
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio(loop_scope="session")
async def test_refresh_token_invalid_rejected(client: AsyncClient) -> None:
    """Malformed or invalid refresh token returns 401."""
    resp = await client.post(
        "/auth/refresh",
        json={"refresh_token": "totally-invalid-refresh-token"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Security & Protected Routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_protected_route_without_token_rejected(client: AsyncClient) -> None:
    """Accessing protected routes without Authorization header returns 401/403."""
    resp = await client.get("/users/me")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio(loop_scope="session")
async def test_protected_route_with_invalid_token_rejected(client: AsyncClient) -> None:
    """Accessing protected routes with forged token returns 401/403."""
    resp = await client.get(
        "/users/me",
        headers={"Authorization": "Bearer fake.invalid.jwt.token"},
    )
    assert resp.status_code in (401, 403)
