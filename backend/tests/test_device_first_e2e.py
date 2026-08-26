"""End-to-end coverage for the device-first trust and live-help contract."""

import pytest
from httpx import AsyncClient


async def _device(
    client: AsyncClient,
    fingerprint: str,
    display_name: str,
) -> dict:
    response = await client.post(
        "/auth/device",
        json={
            "device_fingerprint": fingerprint,
            "display_name": display_name,
        },
    )
    assert response.status_code == 201
    data = response.json()
    data["headers"] = {"Authorization": f"Bearer {data['access_token']}"}
    return data


async def _pair(
    client: AsyncClient,
    owner: dict,
    helper: dict,
    helper_fingerprint: str,
) -> None:
    setup = await client.post(
        "/devices/pairing/setup-code",
        headers=owner["headers"],
        json={},
    )
    assert setup.status_code == 201
    setup_data = setup.json()

    claim = await client.post(
        "/devices/pairing/claim",
        headers=helper["headers"],
        json={
            "setup_code": setup_data["setup_code"],
            "device_fingerprint": helper_fingerprint,
            "friendly_name": "Alex's phone",
            "device_platform": "android",
        },
    )
    assert claim.status_code == 200

    approve = await client.post(
        "/devices/pairing/approve",
        headers=owner["headers"],
        json={"pairing_id": setup_data["pairing_id"]},
    )
    assert approve.status_code == 200
    assert approve.json()["status"] == "accepted"


@pytest.mark.asyncio(loop_scope="session")
async def test_device_first_pairing_and_one_tap_call_cancel(client: AsyncClient) -> None:
    owner = await _device(client, "owner-fingerprint-0001", "Mum")
    helper = await _device(client, "helper-fingerprint-0001", "Alex")
    await _pair(client, owner, helper, "helper-fingerprint-0001")

    owner_devices = await client.get("/devices/", headers=owner["headers"])
    assert owner_devices.status_code == 200
    assert owner_devices.json()["devices"][0]["helper_display_name"] == "Alex"

    helping = await client.get("/devices/helping", headers=helper["headers"])
    assert helping.status_code == 200
    assert helping.json()["entries"][0]["owner_display_name"] == "Mum"

    call = await client.post(
        "/help/call",
        headers=owner["headers"],
        json={"helper_device_fingerprint": "helper-fingerprint-0001"},
    )
    assert call.status_code == 200
    call_data = call.json()
    assert call_data["status"] == "ringing"

    cancelled = await client.post(
        f"/help/call/{call_data['request_id']}/cancel",
        headers=owner["headers"],
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    status = await client.get(
        f"/help/call/{call_data['request_id']}",
        headers=owner["headers"],
    )
    assert status.status_code == 200
    assert status.json()["status"] == "cancelled"


@pytest.mark.asyncio(loop_scope="session")
async def test_acceptance_rechecks_helper_device_and_revoke_is_helpee_only(
    client: AsyncClient,
) -> None:
    owner = await _device(client, "owner-fingerprint-0002", "Mum")
    helper = await _device(client, "helper-fingerprint-0002", "Alex")
    await _pair(client, owner, helper, "helper-fingerprint-0002")

    call = await client.post(
        "/help/call",
        headers=owner["headers"],
        json={"helper_device_fingerprint": "helper-fingerprint-0002"},
    )
    assert call.status_code == 200
    call_data = call.json()

    accepted = await client.post(
        f"/sessions/{call_data['session_id']}/assistance/request/{call_data['request_id']}/respond",
        headers=helper["headers"],
        json={
            "accept": True,
            "helper_device_fingerprint": "helper-fingerprint-0002",
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"

    grant = await client.post(
        f"/sessions/{call_data['session_id']}/remote-control/grant",
        headers=owner["headers"],
        json={"platform": "android_accessibility"},
    )
    assert grant.status_code == 200

    helper_revoke = await client.post(
        f"/sessions/{call_data['session_id']}/remote-control/revoke",
        headers=helper["headers"],
    )
    assert helper_revoke.status_code == 403

    owner_revoke = await client.post(
        f"/sessions/{call_data['session_id']}/remote-control/revoke",
        headers=owner["headers"],
    )
    assert owner_revoke.status_code == 200
    assert owner_revoke.json()["remote_control_granted"] is False


@pytest.mark.asyncio(loop_scope="session")
async def test_helper_cannot_be_called_for_two_helpees_at_once(client: AsyncClient) -> None:
    first_owner = await _device(client, "owner-fingerprint-0003", "Mum")
    second_owner = await _device(client, "owner-fingerprint-0004", "Dad")
    helper = await _device(client, "helper-fingerprint-0003", "Alex")
    await _pair(client, first_owner, helper, "helper-fingerprint-0003")
    await _pair(client, second_owner, helper, "helper-fingerprint-0003")

    first_call = await client.post(
        "/help/call",
        headers=first_owner["headers"],
        json={"helper_device_fingerprint": "helper-fingerprint-0003"},
    )
    assert first_call.status_code == 200

    second_call = await client.post(
        "/help/call",
        headers=second_owner["headers"],
        json={"helper_device_fingerprint": "helper-fingerprint-0003"},
    )
    assert second_call.status_code == 409
