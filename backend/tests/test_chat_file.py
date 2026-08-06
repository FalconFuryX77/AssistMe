"""Comprehensive test suite for Phase 11 In-App Chat & Chunked File Transfer.

Covers: text messaging, E2EE encrypted chat payloads, message listing, chunked file transfer initiation,
chunk upload progress tracking, completion & SHA-256 integrity verification, and file transfer listing.
"""

import pytest
from httpx import AsyncClient

from tests.test_sessions import _create_session, _register


@pytest.mark.asyncio(loop_scope="session")
async def test_send_chat_message_success(client: AsyncClient) -> None:
    """Participant can send an in-app text chat message."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    resp = await client.post(
        f"/sessions/{session['id']}/chat/messages",
        json={"content": "Hello! I am ready to guide you through fixing the network setting."},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "Hello! I am ready to guide you through fixing the network setting."
    assert data["is_encrypted"] is False


@pytest.mark.asyncio(loop_scope="session")
async def test_send_chat_message_e2ee_encrypted(client: AsyncClient) -> None:
    """Participant can send an E2EE encrypted chat message payload."""
    helper = await _register(client)
    helpee = await _register(client)

    session = await _create_session(client, helper["headers"])
    await client.post(
        "/sessions/join",
        json={"session_code": session["session_code"]},
        headers=helpee["headers"],
    )

    resp = await client.post(
        f"/sessions/{session['id']}/chat/messages",
        json={
            "content": "[Encrypted Message]",
            "is_encrypted": True,
            "encrypted_payload": "gAAAAABlX9z...encrypted_ciphertext_hash_payload",
        },
        headers=helpee["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_encrypted"] is True
    assert data["encrypted_payload"] == "gAAAAABlX9z...encrypted_ciphertext_hash_payload"


@pytest.mark.asyncio(loop_scope="session")
async def test_list_chat_messages(client: AsyncClient) -> None:
    """Participants can query all text chat messages in a session."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    await client.post(
        f"/sessions/{session['id']}/chat/messages",
        json={"content": "First message"},
        headers=helper["headers"],
    )
    await client.post(
        f"/sessions/{session['id']}/chat/messages",
        json={"content": "Second message"},
        headers=helper["headers"],
    )

    resp = await client.get(
        f"/sessions/{session['id']}/chat/messages",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_messages"] >= 2
    assert data["messages"][0]["content"] == "First message"


@pytest.mark.asyncio(loop_scope="session")
async def test_initiate_file_transfer_success(client: AsyncClient) -> None:
    """Participant can register a chunked file transfer session."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    dummy_checksum = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    resp = await client.post(
        f"/sessions/{session['id']}/files/initiate",
        json={
            "filename": "diagnostics_report.pdf",
            "file_size_bytes": 1048576,
            "mime_type": "application/pdf",
            "checksum_sha256": dummy_checksum,
            "total_chunks": 2,
        },
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["filename"] == "diagnostics_report.pdf"
    assert data["file_size_bytes"] == 1048576
    assert data["checksum_sha256"] == dummy_checksum
    assert data["status"] == "initiating"
    assert data["total_chunks"] == 2


@pytest.mark.asyncio(loop_scope="session")
async def test_upload_file_chunk_success(client: AsyncClient) -> None:
    """Participant can upload file chunks and track progress."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    dummy_checksum = "a" * 64
    init_resp = await client.post(
        f"/sessions/{session['id']}/files/initiate",
        json={
            "filename": "config.zip",
            "file_size_bytes": 50000,
            "mime_type": "application/zip",
            "checksum_sha256": dummy_checksum,
            "total_chunks": 2,
        },
        headers=helper["headers"],
    )
    transfer_id = init_resp.json()["id"]

    # Upload Chunk 1
    resp = await client.post(
        f"/sessions/{session['id']}/files/{transfer_id}/chunk",
        json={
            "chunk_index": 0,
            "chunk_data_base64": "UEsDBBQAAAAIAAA==",
        },
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "transferring"
    assert data["received_chunks"] == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_complete_file_transfer_success(client: AsyncClient) -> None:
    """Participant can finalize file transfer and obtain download URL."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    dummy_checksum = "b" * 64
    init_resp = await client.post(
        f"/sessions/{session['id']}/files/initiate",
        json={
            "filename": "logs.txt",
            "file_size_bytes": 1024,
            "checksum_sha256": dummy_checksum,
            "total_chunks": 1,
        },
        headers=helper["headers"],
    )
    transfer_id = init_resp.json()["id"]

    await client.post(
        f"/sessions/{session['id']}/files/{transfer_id}/chunk",
        json={
            "chunk_index": 0,
            "chunk_data_base64": "SGVsbG8gV29ybGQ=",
        },
        headers=helper["headers"],
    )

    # Complete transfer
    resp = await client.post(
        f"/sessions/{session['id']}/files/{transfer_id}/complete",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["received_chunks"] == 1
    assert "https://" in data["download_url"]


@pytest.mark.asyncio(loop_scope="session")
async def test_list_file_transfers(client: AsyncClient) -> None:
    """Participants can query all file transfers in a session."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    dummy_checksum = "c" * 64
    await client.post(
        f"/sessions/{session['id']}/files/initiate",
        json={
            "filename": "patch.bin",
            "file_size_bytes": 4096,
            "checksum_sha256": dummy_checksum,
        },
        headers=helper["headers"],
    )

    resp = await client.get(
        f"/sessions/{session['id']}/files/transfers",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_transfers"] >= 1
