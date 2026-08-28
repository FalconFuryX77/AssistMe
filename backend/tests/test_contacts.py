"""Tests for the trusted contacts API.

Covers: create, list, accept/reject, delete, and edge cases.
"""

import pytest
from httpx import AsyncClient

from tests.test_sessions import _register


# ---------------------------------------------------------------------------
# Helper: register a user pair and create a contact between them
# ---------------------------------------------------------------------------


async def _setup_contact_pair(client: AsyncClient) -> tuple[dict, dict, dict]:
    """Register two users and return (user_a_data, user_b_data, contact_data).

    user_a sends a contact request to user_b.
    """
    a_data = await _register(client)
    b_data = await _register(client)

    # A sends contact request to B using user email
    contact_resp = await client.post(
        "/contacts/",
        json={"contact_email": b_data["user"]["email"]},
        headers=a_data["headers"],
    )
    contact_data = contact_resp.json()

    return a_data, b_data, contact_data


# ---------------------------------------------------------------------------
# Create Contact Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_create_contact_success(client: AsyncClient) -> None:
    """Sending a contact request to another user returns 201."""
    a_data, b_data, contact_data = await _setup_contact_pair(client)
    assert contact_data["status"] == "pending"
    assert contact_data["contact_user_id"] == b_data["user"]["id"]


@pytest.mark.asyncio(loop_scope="session")
async def test_create_contact_self_add(client: AsyncClient) -> None:
    """Adding yourself as a contact returns 400."""
    user = await _register(client)
    response = await client.post(
        "/contacts/",
        json={"contact_email": user["user"]["email"]},
        headers=user["headers"],
    )
    assert response.status_code == 400
    assert "yourself" in response.json()["detail"].lower()


@pytest.mark.asyncio(loop_scope="session")
async def test_create_contact_duplicate(client: AsyncClient) -> None:
    """Sending a duplicate contact request returns 400."""
    a_data, b_data, _ = await _setup_contact_pair(client)

    response = await client.post(
        "/contacts/",
        json={"contact_email": b_data["user"]["email"]},
        headers=a_data["headers"],
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"].lower()


@pytest.mark.asyncio(loop_scope="session")
async def test_create_contact_nonexistent_user(client: AsyncClient) -> None:
    """Sending a contact request to a non-existent email returns 404."""
    user = await _register(client)
    response = await client.post(
        "/contacts/",
        json={"contact_email": "nobody_ever@example.com"},
        headers=user["headers"],
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# List Contacts Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_list_contacts(client: AsyncClient) -> None:
    """Listing contacts returns the user's contact relationships."""
    a_data, _, _ = await _setup_contact_pair(client)

    response = await client.get("/contacts/", headers=a_data["headers"])
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.asyncio(loop_scope="session")
async def test_list_contacts_filter_by_status(client: AsyncClient) -> None:
    """Filtering contacts by status works."""
    a_data, _, _ = await _setup_contact_pair(client)

    response = await client.get(
        "/contacts/", params={"status": "pending"}, headers=a_data["headers"]
    )
    assert response.status_code == 200
    for contact in response.json():
        assert contact["status"] == "pending"


# ---------------------------------------------------------------------------
# Accept / Reject Contact Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_accept_contact(client: AsyncClient) -> None:
    """The recipient can accept a contact request."""
    a_data, b_data, contact_data = await _setup_contact_pair(client)
    contact_id = contact_data["id"]

    response = await client.patch(
        f"/contacts/{contact_id}",
        json={"status": "accepted"},
        headers=b_data["headers"],
    )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


@pytest.mark.asyncio(loop_scope="session")
async def test_reject_contact(client: AsyncClient) -> None:
    """The recipient can reject a contact request."""
    a_data, b_data, contact_data = await _setup_contact_pair(client)
    contact_id = contact_data["id"]

    response = await client.patch(
        f"/contacts/{contact_id}",
        json={"status": "rejected"},
        headers=b_data["headers"],
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


@pytest.mark.asyncio(loop_scope="session")
async def test_update_contact_wrong_user(client: AsyncClient) -> None:
    """The sender cannot accept/reject their own request."""
    a_data, _, contact_data = await _setup_contact_pair(client)
    contact_id = contact_data["id"]

    response = await client.patch(
        f"/contacts/{contact_id}",
        json={"status": "accepted"},
        headers=a_data["headers"],
    )
    assert response.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_update_contact_invalid_status(client: AsyncClient) -> None:
    """Invalid status value returns 400."""
    a_data, b_data, contact_data = await _setup_contact_pair(client)
    contact_id = contact_data["id"]

    response = await client.patch(
        f"/contacts/{contact_id}",
        json={"status": "invalid_status"},
        headers=b_data["headers"],
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Delete Contact Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_delete_contact(client: AsyncClient) -> None:
    """Either party can delete a contact."""
    a_data, _, contact_data = await _setup_contact_pair(client)
    contact_id = contact_data["id"]

    response = await client.delete(
        f"/contacts/{contact_id}",
        headers=a_data["headers"],
    )
    assert response.status_code == 204


@pytest.mark.asyncio(loop_scope="session")
async def test_delete_contact_not_found(client: AsyncClient) -> None:
    """Deleting a non-existent contact returns 404."""
    user = await _register(client)
    response = await client.delete(
        "/contacts/00000000-0000-0000-0000-000000000000",
        headers=user["headers"],
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Authorization Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_contacts_require_auth(client: AsyncClient) -> None:
    """Contact endpoints without auth return 401/403."""
    response = await client.get("/contacts/")
    assert response.status_code in (401, 403)
