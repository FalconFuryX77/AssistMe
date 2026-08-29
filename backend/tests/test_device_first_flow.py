"""Tests for the device-first identity + one-tap help flow.

Covers:
  - POST /auth/device bootstrap (create-once identity, silent re-login,
    recovery code shown exactly once, display-name updates)
  - Mutual trust: claim records the helper, approval links both sides,
    /devices/helping exposes the helper's address book
  - POST /help/call: tap-to-ring auto-forms the pair session (no codes),
    enforces trusted-list security, blocks duplicate pending requests
"""

import pytest
from httpx import AsyncClient

from tests.test_sessions import _register

FP_HELPEE = "assistme-device-fp-helpee-000000000001"
FP_HELPER = "assistme-device-fp-helper-000000000002"


async def _bootstrap_device(
    client: AsyncClient,
    fingerprint: str,
    name: str | None = None,
    device_secret: str | None = None,
) -> dict:
    payload = {"device_fingerprint": fingerprint}
    if name is not None:
        payload["display_name"] = name
    if device_secret is not None:
        payload["device_secret"] = device_secret

    resp = await client.post(
        "/auth/device",
        json=payload,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Device bootstrap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_device_bootstrap_creates_identity_once(client: AsyncClient) -> None:
    """First call creates the account + recovery code; second call logs in."""
    first = await _bootstrap_device(client, FP_HELPEE, "Grandma")
    assert first["created"] is True
    assert first["recovery_code"] is not None
    assert len(first["recovery_code"]) == 12
    assert first["display_name"] == "Grandma"
    assert first["access_token"]
    assert first["device_secret"]

    second = await _bootstrap_device(
        client, FP_HELPEE, device_secret=first["device_secret"]
    )
    assert second["created"] is False
    assert second["recovery_code"] is None
    assert second["user_id"] == first["user_id"]
    # Name persists from creation
    assert second["display_name"] == "Grandma"


@pytest.mark.asyncio(loop_scope="session")
async def test_device_bootstrap_updates_display_name(client: AsyncClient) -> None:
    """A later bootstrap can rename the device owner."""
    first = await _bootstrap_device(client, FP_HELPER, "Old Name")
    renamed = await _bootstrap_device(
        client, FP_HELPER, "New Name", device_secret=first["device_secret"]
    )
    assert renamed["user_id"] == first["user_id"]
    assert renamed["display_name"] == "New Name"


@pytest.mark.asyncio(loop_scope="session")
async def test_device_bootstrap_token_works(client: AsyncClient) -> None:
    """The token issued by bootstrap authenticates normal endpoints."""
    boot = await _bootstrap_device(client, FP_HELPEE, "Gran")
    resp = await client.get(
        "/devices/", headers={"Authorization": f"Bearer {boot['access_token']}"}
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio(loop_scope="session")
async def test_device_bootstrap_rejects_short_fingerprint(client: AsyncClient) -> None:
    """Fingerprints below 16 characters are rejected."""
    resp = await client.post(
        "/auth/device", json={"device_fingerprint": "short"}
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Mutual trust via setup-code pairing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_pairing_links_both_sides(client: AsyncClient) -> None:
    """After approve: owner has the contact, helper sees them in /helping."""
    helpee = await _register(client)
    boot_helper = await _bootstrap_device(client, FP_HELPER, "Son")

    # Owner generates the code; helper claims it with their fingerprint.
    code_resp = await client.post(
        "/devices/pairing/setup-code", json={}, headers=helpee["headers"]
    )
    code = code_resp.json()["setup_code"]

    claim = await client.post(
        "/devices/pairing/claim",
        json={
            "setup_code": code,
            "device_fingerprint": FP_HELPER,
            "friendly_name": "Son's Phone",
            "device_platform": "android",
        },
        headers={
            "Authorization": f"Bearer {boot_helper['access_token']}"
        },
    )
    assert claim.status_code == 200, claim.text

    # Owner one-tap approves.
    pending = await client.get("/devices/pairing/pending", headers=helpee["headers"])
    pairing_id = pending.json()["pairings"][0]["pairing_id"]
    approve = await client.post(
        "/devices/pairing/approve",
        json={"pairing_id": pairing_id},
        headers=helpee["headers"],
    )
    assert approve.status_code == 200

    # Owner's list shows the helper device WITH the helper user linked.
    listing = await client.get("/devices/", headers=helpee["headers"])
    devices = listing.json()["devices"]
    assert len(devices) == 1
    assert devices[0]["helper_user_id"] == boot_helper["user_id"]

    # Helper's address book now contains the owner — mutual trust.
    helping = await client.get(
        "/devices/helping",
        headers={"Authorization": f"Bearer {boot_helper['access_token']}"},
    )
    assert helping.status_code == 200
    entries = helping.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["owner_user_id"] == helpee["user"]["id"]
    assert entries[0]["owner_display_name"] is not None


# ---------------------------------------------------------------------------
# One-tap help call
# ---------------------------------------------------------------------------


async def _paired_pair(client: AsyncClient) -> tuple[dict, dict]:
    """Bootstrap a helpee + helper and pair them. Returns (helpee, helper)."""
    helpee = await _register(client)
    helper = {
        "user_id": None,
        "headers": None,
        "fingerprint": FP_HELPER,
    }
    boot = await _bootstrap_device(client, FP_HELPER, "Son")
    helper["user_id"] = boot["user_id"]
    helper["headers"] = {"Authorization": f"Bearer {boot['access_token']}"}

    code = (
        await client.post(
            "/devices/pairing/setup-code", json={}, headers=helpee["headers"]
        )
    ).json()["setup_code"]
    await client.post(
        "/devices/pairing/claim",
        json={
            "setup_code": code,
            "device_fingerprint": FP_HELPER,
            "friendly_name": "Son's Phone",
        },
        headers=helper["headers"],
    )
    pending = await client.get("/devices/pairing/pending", headers=helpee["headers"])
    pairing_id = pending.json()["pairings"][0]["pairing_id"]
    await client.post(
        "/devices/pairing/approve",
        json={"pairing_id": pairing_id},
        headers=helpee["headers"],
    )
    return helpee, helper


@pytest.mark.asyncio(loop_scope="session")
async def test_help_call_auto_forms_session(client: AsyncClient) -> None:
    """Tap-to-ring creates the pair session silently — no codes involved."""
    helpee, helper = await _paired_pair(client)

    call = await client.post(
        "/help/call",
        json={
            "helper_device_fingerprint": FP_HELPER,
            "message": "Phone is acting strange",
        },
        headers=helpee["headers"],
    )
    assert call.status_code == 200, call.text
    data = call.json()
    assert data["status"] == "ringing"
    assert data["request_id"]
    assert data["session_id"]

    # Both participants are in the auto-formed session.
    session = await client.get(
        f"/sessions/{data['session_id']}", headers=helpee["headers"]
    )
    assert session.status_code == 200


@pytest.mark.asyncio(loop_scope="session")
async def test_help_call_requires_trusted_device(client: AsyncClient) -> None:
    """An untrusted fingerprint can never be rung."""
    helpee, _ = await _paired_pair(client)
    stranger_fp = "assistme-device-fp-stranger-0000003"

    call = await client.post(
        "/help/call",
        json={"helper_device_fingerprint": stranger_fp},
        headers=helpee["headers"],
    )
    assert call.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_help_call_accept_and_deny(client: AsyncClient) -> None:
    """Helper accept/deny flows through the existing request pipeline."""
    helpee, helper = await _paired_pair(client)

    call = await client.post(
        "/help/call",
        json={"helper_device_fingerprint": FP_HELPER},
        headers=helpee["headers"],
    )
    request_id = call.json()["request_id"]

    deny = await client.post(
        f"/sessions/{call.json()['session_id']}/assistance/request/{request_id}/respond",
        json={"accept": False},
        headers=helper["headers"],
    )
    assert deny.status_code == 200
    assert deny.json()["status"] == "denied"

    # A denied request frees the line: ring again and accept this time.
    call2 = await client.post(
        "/help/call",
        json={"helper_device_fingerprint": FP_HELPER},
        headers=helpee["headers"],
    )
    assert call2.status_code == 200
    accept = await client.post(
        f"/sessions/{call2.json()['session_id']}/assistance/request/"
        f"{call2.json()['request_id']}/respond",
        json={"accept": True, "helper_device_fingerprint": FP_HELPER},
        headers=helper["headers"],
    )
    assert accept.status_code == 200
    assert accept.json()["status"] == "accepted"
