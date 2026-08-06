"""Comprehensive test suite for Phase 7 Adaptive Streaming & Optimization.

Covers: manual stream scaling (1080p, 720p, 480p, 360p), automated bitrate & resolution adaptation,
frame rate throttling under high RTT/packet loss, client network metrics reporting, and configuration queries.
"""

import pytest
from httpx import AsyncClient

from tests.test_sessions import _create_session, _register


@pytest.mark.asyncio(loop_scope="session")
async def test_manual_stream_adaptation_success(client: AsyncClient) -> None:
    """Participant can manually configure video resolution, bitrate, and frame rate."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/streaming/adapt",
        json={
            "video_resolution": "1080p",
            "video_bitrate_kbps": 3000,
            "video_fps": 60,
        },
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["video_resolution"] == "1080p"
    assert data["video_bitrate_kbps"] == 3000
    assert data["video_fps"] == 60


@pytest.mark.asyncio(loop_scope="session")
async def test_manual_stream_adaptation_invalid_resolution(client: AsyncClient) -> None:
    """Invalid video_resolution string returns 422 validation error."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/streaming/adapt",
        json={"video_resolution": "4k"},
        headers=helper["headers"],
    )
    assert resp.status_code == 422


@pytest.mark.asyncio(loop_scope="session")
async def test_network_metrics_auto_adaptation_high_quality(client: AsyncClient) -> None:
    """Ideal network conditions (RTT < 100ms, loss < 2%) auto-adapt stream to 1080p @ 30 FPS / 3000 kbps."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/streaming/metrics",
        json={"rtt_ms": 35.0, "jitter_ms": 2.1, "packet_loss_percent": 0.5},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["video_resolution"] == "1080p"
    assert data["video_bitrate_kbps"] == 3000
    assert data["video_fps"] == 30
    assert data["auto_adapted"] is True


@pytest.mark.asyncio(loop_scope="session")
async def test_network_metrics_auto_adaptation_medium_quality(client: AsyncClient) -> None:
    """Moderate network constraints (RTT 150ms, loss 3%) auto-adapt stream to 720p @ 30 FPS / 1500 kbps."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/streaming/metrics",
        json={"rtt_ms": 150.0, "jitter_ms": 12.0, "packet_loss_percent": 3.0},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["video_resolution"] == "720p"
    assert data["video_bitrate_kbps"] == 1500
    assert data["video_fps"] == 30


@pytest.mark.asyncio(loop_scope="session")
async def test_network_metrics_auto_adaptation_low_quality(client: AsyncClient) -> None:
    """Poor network constraints (RTT 350ms, loss 8%) auto-adapt stream to 480p @ 15 FPS / 600 kbps."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/streaming/metrics",
        json={"rtt_ms": 350.0, "jitter_ms": 25.0, "packet_loss_percent": 8.0},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["video_resolution"] == "480p"
    assert data["video_bitrate_kbps"] == 600
    assert data["video_fps"] == 15


@pytest.mark.asyncio(loop_scope="session")
async def test_network_metrics_auto_adaptation_degraded(client: AsyncClient) -> None:
    """Severe network degradation (RTT > 500ms or loss > 15%) auto-adapts stream to 360p @ 10 FPS / 250 kbps."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.post(
        f"/sessions/{session['id']}/streaming/metrics",
        json={"rtt_ms": 650.0, "jitter_ms": 50.0, "packet_loss_percent": 18.5},
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["video_resolution"] == "360p"
    assert data["video_bitrate_kbps"] == 250
    assert data["video_fps"] == 10


@pytest.mark.asyncio(loop_scope="session")
async def test_get_stream_config(client: AsyncClient) -> None:
    """Participants can query active WebRTC video streaming configuration."""
    helper = await _register(client)
    session = await _create_session(client, helper["headers"])

    resp = await client.get(
        f"/sessions/{session['id']}/streaming/config",
        headers=helper["headers"],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["video_resolution"] == "720p"
    assert data["video_bitrate_kbps"] == 1500
    assert data["video_fps"] == 30
