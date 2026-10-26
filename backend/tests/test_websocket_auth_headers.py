from types import SimpleNamespace

import pytest

from api.routers import device_ws, session_ws


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Database:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, _statement):
        return _Result(self.value)


class _DatabaseFactory:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return _Database(self.value)


class _Socket:
    def __init__(self, authorization="", query_token=None):
        self.headers = {"authorization": authorization} if authorization else {}
        self.query_params = {"token": query_token} if query_token else {}


@pytest.mark.asyncio(loop_scope="session")
async def test_session_websocket_requires_bearer_header_and_active_user(monkeypatch):
    active_user = SimpleNamespace(id="user-1", is_active=True)
    monkeypatch.setattr(session_ws, "decode_access_token", lambda token: {"sub": "user-1"})
    monkeypatch.setattr(session_ws, "async_session_factory", _DatabaseFactory(active_user))

    user = await session_ws._authenticate_ws(_Socket("Bearer valid-token"))
    assert user is active_user

    # Query strings are intentionally no longer an authentication transport.
    query_only = await session_ws._authenticate_ws(_Socket(query_token="valid-token"))
    assert query_only is None

    inactive_user = SimpleNamespace(id="user-1", is_active=False)
    monkeypatch.setattr(session_ws, "async_session_factory", _DatabaseFactory(inactive_user))
    assert await session_ws._authenticate_ws(_Socket("Bearer valid-token")) is None


@pytest.mark.asyncio(loop_scope="session")
async def test_device_websocket_requires_bearer_header_and_active_user(monkeypatch):
    active_user = SimpleNamespace(id="user-2", is_active=True)
    monkeypatch.setattr(device_ws, "decode_access_token", lambda token: {"sub": "user-2"})
    monkeypatch.setattr(device_ws, "async_session_factory", _DatabaseFactory(active_user))

    assert await device_ws._authenticated_user_id(_Socket("Bearer valid-token")) == "user-2"
    assert await device_ws._authenticated_user_id(_Socket(query_token="valid-token")) is None

    inactive_user = SimpleNamespace(id="user-2", is_active=False)
    monkeypatch.setattr(device_ws, "async_session_factory", _DatabaseFactory(inactive_user))
    assert await device_ws._authenticated_user_id(_Socket("Bearer valid-token")) is None
