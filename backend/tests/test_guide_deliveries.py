"""Post-session encrypted guide hand-off between the two session participants."""

import base64

import pytest
from httpx import AsyncClient

from tests.test_sessions import _create_session, _register


async def _paired_session(client: AsyncClient) -> tuple[dict, dict, dict]:
    helper = await _register(client)
    helpee = await _register(client)
    session = await _create_session(client, helper["headers"])
    joined = await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )
    assert joined.status_code == 200
    return helper, helpee, session


@pytest.mark.asyncio(loop_scope="session")
async def test_helper_uploads_and_helpee_downloads_once(client: AsyncClient) -> None:
    helper, helpee, session = await _paired_session(client)
    sealed = base64.b64encode(b"\x00" * 12 + b"opaque-ciphertext-bytes").decode()

    created = await client.post(
        "/guide-deliveries",
        json={"session_id": session["id"], "ciphertext": sealed},
        headers=helper["headers"],
    )
    assert created.status_code == 201

    # The sender does not see it as pending for itself.
    own = await client.get("/guide-deliveries/pending", headers=helper["headers"])
    assert own.json() == []

    pending = await client.get("/guide-deliveries/pending", headers=helpee["headers"])
    assert pending.status_code == 200
    items = pending.json()
    assert len(items) == 1 and items[0]["session_id"] == session["id"]

    fetched = await client.get(
        f"/guide-deliveries/{items[0]['id']}", headers=helpee["headers"]
    )
    assert fetched.status_code == 200
    assert fetched.json()["ciphertext"] == sealed

    # Only the recipient may read or acknowledge it.
    stranger = await client.get(
        f"/guide-deliveries/{items[0]['id']}", headers=helper["headers"]
    )
    assert stranger.status_code == 404

    acked = await client.delete(
        f"/guide-deliveries/{items[0]['id']}", headers=helpee["headers"]
    )
    assert acked.status_code == 204
    again = await client.get("/guide-deliveries/pending", headers=helpee["headers"])
    assert again.json() == []


@pytest.mark.asyncio(loop_scope="session")
async def test_retry_replaces_previous_upload(client: AsyncClient) -> None:
    helper, helpee, session = await _paired_session(client)
    for body in (b"first", b"second"):
        response = await client.post(
            "/guide-deliveries",
            json={"session_id": session["id"], "ciphertext": base64.b64encode(body).decode()},
            headers=helper["headers"],
        )
        assert response.status_code == 201
    pending = (await client.get("/guide-deliveries/pending", headers=helpee["headers"])).json()
    assert len(pending) == 1
    fetched = await client.get(f"/guide-deliveries/{pending[0]['id']}", headers=helpee["headers"])
    assert base64.b64decode(fetched.json()["ciphertext"]) == b"second"


@pytest.mark.asyncio(loop_scope="session")
async def test_non_participant_cannot_upload(client: AsyncClient) -> None:
    _, _, session = await _paired_session(client)
    outsider = await _register(client)
    response = await client.post(
        "/guide-deliveries",
        json={"session_id": session["id"], "ciphertext": base64.b64encode(b"x").decode()},
        headers=outsider["headers"],
    )
    assert response.status_code == 403


@pytest.mark.asyncio(loop_scope="session")
async def test_rejects_non_base64(client: AsyncClient) -> None:
    helper, _, session = await _paired_session(client)
    response = await client.post(
        "/guide-deliveries",
        json={"session_id": session["id"], "ciphertext": "not base64!!"},
        headers=helper["headers"],
    )
    assert response.status_code == 400
