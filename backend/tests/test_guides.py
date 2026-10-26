"""Tests for the Session Guide and Step-by-Step Visual Recall system."""

import pytest
from httpx import AsyncClient

from tests.test_sessions import _register


@pytest.mark.asyncio(loop_scope="session")
async def test_create_and_list_guides(client: AsyncClient) -> None:
    """A user can manually create and retrieve a session guide."""
    user = await _register(client)
    headers = user["headers"]

    # 1. Create a guide
    create_payload = {
        "title": "How to Change Phone Language",
        "summary": "Steps to switch language to English in Settings.",
        "category": "settings",
        "steps": [
            {
                "step_number": 1,
                "title": "Open Settings",
                "instruction": "Tap on the Settings gear icon on your home screen.",
            },
            {
                "step_number": 2,
                "title": "Select Language",
                "instruction": "Tap General Management, then tap Language.",
            },
        ],
    }

    resp = await client.post("/guides", json=create_payload, headers=headers)
    assert resp.status_code == 201
    guide = resp.json()
    guide_id = guide["id"]
    assert guide["title"] == "How to Change Phone Language"
    assert guide["steps_count"] == 2
    assert len(guide["steps"]) == 2
    assert guide["steps"][0]["step_number"] == 1
    assert guide["steps"][1]["title"] == "Select Language"

    # 2. List guides
    list_resp = await client.get("/guides", headers=headers)
    assert list_resp.status_code == 200
    guides = list_resp.json()
    assert len(guides) >= 1
    assert any(g["id"] == guide_id for g in guides)

    # 3. Get single guide details
    detail_resp = await client.get(f"/guides/{guide_id}", headers=headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["id"] == guide_id
    assert len(detail["steps"]) == 2

    # 4. Delete guide
    del_resp = await client.delete(f"/guides/{guide_id}", headers=headers)
    assert del_resp.status_code == 204

    # 5. Verify deleted
    get_again = await client.get(f"/guides/{guide_id}", headers=headers)
    assert get_again.status_code == 404


@pytest.mark.asyncio(loop_scope="session")
async def test_create_guide_rejects_uploaded_images(client: AsyncClient) -> None:
    """Guide screenshots are private on-device data, not API payloads."""
    user = await _register(client)
    response = await client.post(
        "/guides",
        json={
            "title": "Private guide",
            "steps": [
                {
                    "step_number": 1,
                    "instruction": "Tap Continue",
                    "image_url": "data:image/jpeg;base64,private-screen-data",
                }
            ],
        },
        headers=user["headers"],
    )
    assert response.status_code == 422
    assert "on-device" in response.json()["detail"]


@pytest.mark.asyncio(loop_scope="session")
async def test_legacy_cloud_guide_synthesis_is_disabled(client: AsyncClient) -> None:
    """Legacy screenshot/transcript synthesis must never forward user data to a cloud model."""
    user = await _register(client)
    headers = user["headers"]
    # Create dummy session first
    sess_resp = await client.post("/sessions/", json={"title": "Test Session"}, headers=headers)
    assert sess_resp.status_code == 201
    actual_session_id = sess_resp.json()["id"]

    # Provide candidate keyframes with duplicates (e.g., test scribbles)
    synth_payload = {
        "title": "Wi-Fi Setup Guide",
        "transcript_text": "First open Settings. Then tap Connections. Select your home network and enter the password.",
        "keyframes": [
            {
                "title": "Frame 1",
                "instruction": "Open Settings",
                "image_url": "data:image/jpeg;base64,aaa111",
            },
            {
                "title": "Duplicate Frame (should be filtered)",
                "instruction": "Scribble on same screen",
                "image_url": "data:image/jpeg;base64,aaa111",  # Same image hash
            },
            {
                "title": "Frame 2",
                "instruction": "Tap Wi-Fi",
                "image_url": "data:image/jpeg;base64,bbb222",
            },
        ],
    }

    resp = await client.post(
        f"/sessions/{actual_session_id}/guide/generate",
        json=synth_payload,
        headers=headers,
    )
    assert resp.status_code == 410
    assert "on-device" in resp.json()["detail"]
