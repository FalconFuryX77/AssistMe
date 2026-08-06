from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_register_endpoint_returns_placeholder() -> None:
    response = client.post(
        "/auth/register",
        json={"email": "user@example.com", "password": "secret123"},
    )
    assert response.status_code == 200
    assert response.json() == {"message": "registration endpoint placeholder"}


def test_login_endpoint_returns_placeholder() -> None:
    response = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "secret123"},
    )
    assert response.status_code == 200
    assert response.json() == {"message": "login endpoint placeholder"}
