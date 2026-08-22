"""Tests for the trusted-device pairing and security-focused assistance flow.

Covers: device pairing (initiate/confirm with password gate), trusted-list
management (password-protected revoke), device identity verification, the
one-click help request flow (only trusted devices can assist), default
overlay-only acceptance, and escalation gated by explicit disclaimer acceptance.
"""

import pytest
from httpx import AsyncClient

from tests.test_sessions import _create_session, _register

DEVICE_FP = "device-fingerprint-abc123def4567890"


# ---------------------------------------------------------------------------
# Trusted device pairing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_initiate_pairing_returns_code(client: AsyncClient) -> None:
    """Initiating pairing returns a 6-digit code + expiry."""
    user = await _register(client)
    resp = await client.post(
        "/devices/pairing/initiate",
        json={
            "device_fingerprint": DEVICE_FP,
            "friendly_name": "Dad's Phone",
            "device_platform": "android",
        },
        headers=user["headers"],
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["pairing_code"]) == 6
    assert data["pairing_code"].isdigit()
    assert data["expires_at"]


@pytest.mark.asyncio(loop_scope="session")
async def test_confirm_pairing_requires_password(client: AsyncClient) -> None:
    """Confirming pairing fails without the correct password."""
    user = await _register(client)
    await client.post(
        "/devices/pairing/initiate",
        json={"device_fingerprint": DEVICE_FP, "friendly_name": "Dad's Phone"},
        headers=user["headers"],
    )
    resp = await client.post(
        "/devices/pairing/confirm",
        json={"pairing_code": "000000", "password": "WrongPass9"},
        headers=user["headers"],
    )
    assert resp.status_code == 401
    assert "password" in resp.json()["detail"].lower()


@pytest.mark.asyncio(loop_scope="session")
async def test_confirm_pairing_success_flow(client: AsyncClient) -> None:
    """Full pairing flow: initiate → confirm with password → device trusted."""
    user = await _register(client)
    init = await client.post(
        "/devices/pairing/initiate",
        json={
            "device_fingerprint": DEVICE_FP,
            "friendly_name": "Dad's Phone",
            "device_platform": "android",
        },
        headers=user["headers"],
    )
    code = init.json()["pairing_code"]

    confirm = await client.post(
        "/devices/pairing/confirm",
        json={"pairing_code": code, "password": "SecureP1"},
        headers=user["headers"],
    )
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "accepted"

    listing = await client.get("/devices/", headers=user["headers"])
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["devices"][0]["device_fingerprint"] == DEVICE_FP


@pytest.mark.asyncio(loop_scope="session")
async def test_confirm_pairing_wrong_code(client: AsyncClient) -> None:
    """A wrong pairing code is rejected even with the correct password."""
    user = await _register(client)
    await client.post(
        "/devices/pairing/initiate",
        json={"device_fingerprint": DEVICE_FP},
        headers=user["headers"],
    )
    resp = await client.post(
        "/devices/pairing/confirm",
        json={"pairing_code": "999999", "password": "SecureP1"},
        headers=user["headers"],
    )
    assert resp.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_revoke_device_one_tap(client: AsyncClient) -> None:
    """Revoking a trusted device is a one-tap action (no password)."""
    user = await _register(client)
    init = await client.post(
        "/devices/pairing/initiate",
        json={"device_fingerprint": DEVICE_FP},
        headers=user["headers"],
    )
    await client.post(
        "/devices/pairing/confirm",
        json={"pairing_code": init.json()["pairing_code"], "password": "SecureP1"},
        headers=user["headers"],
    )
    listing = await client.get("/devices/", headers=user["headers"])
    device_id = listing.json()["devices"][0]["id"]

    resp = await client.delete(
        f"/devices/{device_id}",
        headers=user["headers"],
    )
    assert resp.status_code == 204
    listing = await client.get("/devices/", headers=user["headers"])
    assert listing.json()["total"] == 0


@pytest.mark.asyncio(loop_scope="session")
async def test_device_identity_verification(client: AsyncClient) -> None:
    """Device identity endpoint reflects trusted status."""
    user = await _register(client)
    resp = await client.post(
        "/devices/identity",
        json={"device_fingerprint": DEVICE_FP},
        headers=user["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["is_trusted"] is False

    init = await client.post(
        "/devices/pairing/initiate",
        json={"device_fingerprint": DEVICE_FP},
        headers=user["headers"],
    )
    await client.post(
        "/devices/pairing/confirm",
        json={"pairing_code": init.json()["pairing_code"], "password": "SecureP1"},
        headers=user["headers"],
    )
    resp = await client.post(
        "/devices/identity",
        json={"device_fingerprint": DEVICE_FP},
        headers=user["headers"],
    )
    assert resp.json()["is_trusted"] is True
    assert resp.json()["status"] == "accepted"


# ---------------------------------------------------------------------------
# Helper-driven setup code flow (no password on the owner's side)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_setup_code_generation(client: AsyncClient) -> None:
    """Owner can generate a setup code to read aloud (no fingerprint needed)."""
    user = await _register(client)
    resp = await client.post(
        "/devices/pairing/setup-code",
        json={},
        headers=user["headers"],
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["setup_code"]) == 6
    assert data["setup_code"].isdigit()
    assert data["pairing_id"]
    assert data["expires_at"]


@pytest.mark.asyncio(loop_scope="session")
async def test_setup_code_claim_binds_helper(client: AsyncClient) -> None:
    """A helper who hears the code can claim it and bind their device."""
    owner = await _register(client)
    helper = await _register(client)

    code_resp = await client.post(
        "/devices/pairing/setup-code",
        json={},
        headers=owner["headers"],
    )
    code = code_resp.json()["setup_code"]

    resp = await client.post(
        "/devices/pairing/claim",
        json={
            "setup_code": code,
            "device_fingerprint": DEVICE_FP,
            "friendly_name": "Son's Phone",
            "device_platform": "android",
        },
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"

    # The owner now sees it as a pending pairing awaiting approval
    pending = await client.get("/devices/pairing/pending", headers=owner["headers"])
    assert pending.status_code == 200
    assert pending.json()["total"] == 1
    assert pending.json()["pairings"][0]["friendly_name"] == "Son's Phone"


@pytest.mark.asyncio(loop_scope="session")
async def test_setup_code_claim_wrong_code(client: AsyncClient) -> None:
    """Claiming with a wrong setup code is rejected."""
    owner = await _register(client)
    helper = await _register(client)
    await client.post("/devices/pairing/setup-code", json={}, headers=owner["headers"])

    resp = await client.post(
        "/devices/pairing/claim",
        json={
            "setup_code": "000000",
            "device_fingerprint": DEVICE_FP,
        },
        headers=helper["headers"],
    )
    assert resp.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_setup_code_approve_one_tap(client: AsyncClient) -> None:
    """Owner approves with one tap and NO password — device becomes trusted."""
    owner = await _register(client)
    helper = await _register(client)

    code = (
        await client.post("/devices/pairing/setup-code", json={}, headers=owner["headers"])
    ).json()["setup_code"]
    claim = await client.post(
        "/devices/pairing/claim",
        json={
            "setup_code": code,
            "device_fingerprint": DEVICE_FP,
            "friendly_name": "Son's Phone",
        },
        headers=helper["headers"],
    )
    pairing_id = claim.json()["pairing_id"]

    approve = await client.post(
        "/devices/pairing/approve",
        json={"pairing_id": pairing_id},
        headers=owner["headers"],
    )
    assert approve.status_code == 200
    assert approve.json()["status"] == "accepted"
    assert approve.json()["device_fingerprint"] == DEVICE_FP

    listing = await client.get("/devices/", headers=owner["headers"])
    assert listing.json()["total"] == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_setup_code_approve_wrong_owner(client: AsyncClient) -> None:
    """A stranger cannot approve a pairing that belongs to someone else."""
    owner = await _register(client)
    helper = await _register(client)
    stranger = await _register(client)

    code = (
        await client.post("/devices/pairing/setup-code", json={}, headers=owner["headers"])
    ).json()["setup_code"]
    claim = await client.post(
        "/devices/pairing/claim",
        json={"setup_code": code, "device_fingerprint": DEVICE_FP},
        headers=helper["headers"],
    )
    pairing_id = claim.json()["pairing_id"]

    resp = await client.post(
        "/devices/pairing/approve",
        json={"pairing_id": pairing_id},
        headers=stranger["headers"],
    )
    assert resp.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_full_helper_driven_setup_flow(client: AsyncClient) -> None:
    """End-to-end: code → claim → pending → approve → identity trusted."""
    owner = await _register(client)
    helper = await _register(client)

    # 1. Owner (elderly) generates a code and reads it aloud
    code_resp = await client.post(
        "/devices/pairing/setup-code", json={}, headers=owner["headers"]
    )
    code = code_resp.json()["setup_code"]

    # 2. Helper (child) enters the code on their own phone
    claim = await client.post(
        "/devices/pairing/claim",
        json={
            "setup_code": code,
            "device_fingerprint": DEVICE_FP,
            "friendly_name": "Son's Phone",
            "device_platform": "android",
        },
        headers=helper["headers"],
    )
    assert claim.status_code == 200

    # 3. Owner sees the pending pairing and taps Allow
    pending = await client.get("/devices/pairing/pending", headers=owner["headers"])
    pairing_id = pending.json()["pairings"][0]["pairing_id"]
    approve = await client.post(
        "/devices/pairing/approve",
        json={"pairing_id": pairing_id},
        headers=owner["headers"],
    )
    assert approve.status_code == 200

    # 4. The helper's device is now trusted for the owner
    listing = await client.get("/devices/", headers=owner["headers"])
    assert listing.json()["total"] == 1

    identity = await client.post(
        "/devices/identity",
        json={"device_fingerprint": DEVICE_FP},
        headers=owner["headers"],
    )
    assert identity.json()["is_trusted"] is True


# ---------------------------------------------------------------------------
# One-click help request (trusted devices only)
# ---------------------------------------------------------------------------


async def _trusted_helpee_pairing(client: AsyncClient, helpee_headers: dict) -> None:
    """Pair the helper's device fingerprint into the helpee's trusted list."""
    init = await client.post(
        "/devices/pairing/initiate",
        json={"device_fingerprint": DEVICE_FP, "friendly_name": "Helper Phone"},
        headers=helpee_headers,
    )
    await client.post(
        "/devices/pairing/confirm",
        json={"pairing_code": init.json()["pairing_code"], "password": "SecureP1"},
        headers=helpee_headers,
    )


async def _setup_session_with_helpee(
    client: AsyncClient, helper: dict, helpee: dict
) -> dict:
    """Create a session with the helper as creator and the helpee joined."""
    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )
    return session


@pytest.mark.asyncio(loop_scope="session")
async def test_request_help_rejected_for_untrusted_device(client: AsyncClient) -> None:
    """A helper whose device is NOT trusted cannot receive a help request."""
    helper = await _register(client)
    helpee = await _register(client)
    session = await _setup_session_with_helpee(client, helper, helpee)

    resp = await client.post(
        f"/sessions/{session['id']}/assistance/request",
        json={
            "helper_user_id": helper["user"]["id"],
            "helper_device_fingerprint": "untrusted-fingerprint-1234567890",
        },
        headers=helpee["headers"],
    )
    assert resp.status_code == 403
    assert "trusted" in resp.json()["detail"].lower()


@pytest.mark.asyncio(loop_scope="session")
async def test_request_help_flow_full(client: AsyncClient) -> None:
    """Trusted helper: request → pending → accept grants overlay-only."""
    helper = await _register(client)
    helpee = await _register(client)
    await _trusted_helpee_pairing(client, helpee["headers"])
    session = await _setup_session_with_helpee(client, helper, helpee)

    resp = await client.post(
        f"/sessions/{session['id']}/assistance/request",
        json={
            "helper_user_id": helper["user"]["id"],
            "helper_device_fingerprint": DEVICE_FP,
        },
        headers=helpee["headers"],
    )
    assert resp.status_code == 201
    request = resp.json()
    assert request["status"] == "pending"
    assert request["initial_capabilities"] == ["overlay_draw"]

    # Helper accepts
    resp = await client.post(
        f"/sessions/{session['id']}/assistance/request/{request['id']}/respond",
        json={"accept": True, "helper_device_fingerprint": DEVICE_FP},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"


@pytest.mark.asyncio(loop_scope="session")
async def test_request_help_can_be_denied(client: AsyncClient) -> None:
    """Helper can deny an assistance request."""
    helper = await _register(client)
    helpee = await _register(client)
    await _trusted_helpee_pairing(client, helpee["headers"])
    session = await _setup_session_with_helpee(client, helper, helpee)

    resp = await client.post(
        f"/sessions/{session['id']}/assistance/request",
        json={
            "helper_user_id": helper["user"]["id"],
            "helper_device_fingerprint": DEVICE_FP,
        },
        headers=helpee["headers"],
    )
    request_id = resp.json()["id"]

    resp = await client.post(
        f"/sessions/{session['id']}/assistance/request/{request_id}/respond",
        json={"accept": False},
        headers=helper["headers"],
    )
    assert resp.json()["status"] == "denied"


@pytest.mark.asyncio(loop_scope="session")
async def test_duplicate_pending_request_conflict(client: AsyncClient) -> None:
    """A second pending request for the same session is a 409."""
    helper = await _register(client)
    helpee = await _register(client)
    await _trusted_helpee_pairing(client, helpee["headers"])
    session = await _setup_session_with_helpee(client, helper, helpee)

    payload = {
        "helper_user_id": helper["user"]["id"],
        "helper_device_fingerprint": DEVICE_FP,
    }
    resp = await client.post(
        f"/sessions/{session['id']}/assistance/request", json=payload, headers=helpee["headers"]
    )
    assert resp.status_code == 201

    resp = await client.post(
        f"/sessions/{session['id']}/assistance/request", json=payload, headers=helpee["headers"]
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Escalation with risk disclaimer
# ---------------------------------------------------------------------------


async def _accepted_request(client: AsyncClient, helper: dict, helpee: dict) -> dict:
    """Set up an accepted assistance request."""
    await _trusted_helpee_pairing(client, helpee["headers"])
    session = await _setup_session_with_helpee(client, helper, helpee)
    resp = await client.post(
        f"/sessions/{session['id']}/assistance/request",
        json={
            "helper_user_id": helper["user"]["id"],
            "helper_device_fingerprint": DEVICE_FP,
        },
        headers=helpee["headers"],
    )
    request_id = resp.json()["id"]
    await client.post(
        f"/sessions/{session['id']}/assistance/request/{request_id}/respond",
        json={"accept": True, "helper_device_fingerprint": DEVICE_FP},
        headers=helper["headers"],
    )
    return session


@pytest.mark.asyncio(loop_scope="session")
async def test_escalation_requires_explicit_disclaimer(client: AsyncClient) -> None:
    """Escalation is rejected unless the helpee explicitly accepts the risks."""
    helper = await _register(client)
    helpee = await _register(client)
    session = await _accepted_request(client, helper, helpee)

    # Helper requests tap control
    resp = await client.post(
        f"/sessions/{session['id']}/assistance/escalation",
        json={"target_capabilities": ["tap", "drag"]},
        headers=helper["headers"],
    )
    assert resp.status_code == 201
    escalation = resp.json()
    assert escalation["status"] == "pending"
    assert "Risks" in escalation["disclaimer_text"]
    assert "control your device" in escalation["disclaimer_text"].lower()

    # Helpee accepts WITHOUT accepting disclaimer → rejected
    resp = await client.post(
        f"/sessions/{session['id']}/assistance/escalation/{escalation['id']}/respond",
        json={"accept": True, "accept_disclaimer": False},
        headers=helpee["headers"],
    )
    assert resp.status_code == 400
    assert "risks" in resp.json()["detail"].lower()


@pytest.mark.asyncio(loop_scope="session")
async def test_escalation_granted_with_disclaimer(client: AsyncClient) -> None:
    """Escalation is granted only when helpee accepts the stated risks."""
    helper = await _register(client)
    helpee = await _register(client)
    session = await _accepted_request(client, helper, helpee)

    resp = await client.post(
        f"/sessions/{session['id']}/assistance/escalation",
        json={"target_capabilities": ["tap"]},
        headers=helper["headers"],
    )
    escalation = resp.json()

    resp = await client.post(
        f"/sessions/{session['id']}/assistance/escalation/{escalation['id']}/respond",
        json={"accept": True, "accept_disclaimer": True},
        headers=helpee["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "approved"
    assert data["disclaimer_accepted"] is True
    assert data["granted_capabilities"] == ["tap"]


@pytest.mark.asyncio(loop_scope="session")
async def test_escalation_rejected_cleanly(client: AsyncClient) -> None:
    """Helpee can reject an escalation outright."""
    helper = await _register(client)
    helpee = await _register(client)
    session = await _accepted_request(client, helper, helpee)

    resp = await client.post(
        f"/sessions/{session['id']}/assistance/escalation",
        json={"target_capabilities": ["tap", "drag"]},
        headers=helper["headers"],
    )
    escalation = resp.json()

    resp = await client.post(
        f"/sessions/{session['id']}/assistance/escalation/{escalation['id']}/respond",
        json={"accept": False, "accept_disclaimer": False},
        headers=helpee["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert resp.json()["granted_capabilities"] == []


@pytest.mark.asyncio(loop_scope="session")
async def test_escalation_requires_helper_role(client: AsyncClient) -> None:
    """Only a helper (not the helpee) can request escalation."""
    helper = await _register(client)
    helpee = await _register(client)
    session = await _accepted_request(client, helper, helpee)

    resp = await client.post(
        f"/sessions/{session['id']}/assistance/escalation",
        json={"target_capabilities": ["tap"]},
        headers=helpee["headers"],
    )
    assert resp.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_escalation_invalid_capability(client: AsyncClient) -> None:
    """Requesting an invalid capability is rejected at validation."""
    helper = await _register(client)
    helpee = await _register(client)
    session = await _accepted_request(client, helper, helpee)

    resp = await client.post(
        f"/sessions/{session['id']}/assistance/escalation",
        json={"target_capabilities": ["hack", "exploit"]},
        headers=helper["headers"],
    )
    assert resp.status_code == 422
