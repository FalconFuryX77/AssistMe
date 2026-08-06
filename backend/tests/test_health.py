"""Tests for the health check endpoint."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio(loop_scope="session")
async def test_health_endpoint_returns_ok(client: AsyncClient) -> None:
    """Health check returns 200 with status ok."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
