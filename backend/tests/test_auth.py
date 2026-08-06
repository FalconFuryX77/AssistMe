from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_register_endpoint_returns_token() -> None:
    response = client.post(
        "/auth/register",
        json={"email": "user@example.com", "password": "secret123"},
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


def test_login_endpoint_returns_token() -> None:
    response = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "secret123"},
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]
