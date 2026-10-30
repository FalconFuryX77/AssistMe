"""Signaling between phones whose sockets live on different API workers."""

import json

import pytest

import core.realtime_bus as bus
from api.routers import session_ws


class _FakeRedis:
    """Just enough of redis.asyncio.Redis for presence and parked signals."""

    def __init__(self) -> None:
        self.sets: dict[str, set[str]] = {}
        self.lists: dict[str, list[str]] = {}
        self.published: list[tuple[str, dict]] = []

    async def sadd(self, key, *values):
        self.sets.setdefault(key, set()).update(values)

    async def srem(self, key, *values):
        self.sets.get(key, set()).difference_update(values)

    async def smembers(self, key):
        return set(self.sets.get(key, set()))

    async def expire(self, key, seconds):
        return True

    async def rpush(self, key, *values):
        self.lists.setdefault(key, []).extend(values)

    async def ltrim(self, key, start, end):
        items = self.lists.get(key, [])
        self.lists[key] = items[start:] if end == -1 else items[start : end + 1]

    async def lrange(self, key, start, end):
        return list(self.lists.get(key, []))

    async def delete(self, key):
        self.lists.pop(key, None)

    async def publish(self, channel, message):
        self.published.append((channel, json.loads(message)["payload"]))


@pytest.fixture
def fake_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(bus, "_redis", lambda: fake)
    session_ws._pending_signals.clear()
    yield fake
    session_ws._pending_signals.clear()


def _offer(sender: str) -> dict:
    return {"type": "signal_offer", "sender_user_id": sender, "sdp": {"type": "offer"}}


@pytest.mark.asyncio(loop_scope="session")
async def test_offer_is_published_when_peer_is_on_another_worker(fake_redis) -> None:
    await bus.presence_add("s1", "helper")

    parked = await session_ws._relay_to_absent_peer("s1", "helpee", _offer("helpee"), limit=64)

    assert parked is False
    assert fake_redis.published[-1][0] == "assistme:session:s1"
    assert fake_redis.published[-1][1]["message"]["type"] == "signal_offer"
    assert await bus.take_parked_signals("s1", "helper") == []


@pytest.mark.asyncio(loop_scope="session")
async def test_offer_is_parked_until_peer_connects_anywhere(fake_redis) -> None:
    await bus.presence_add("s2", "helpee")  # only the sender is connected

    parked = await session_ws._relay_to_absent_peer("s2", "helpee", _offer("helpee"), limit=64)

    assert parked is True
    # The helper connects later, possibly through another worker.
    delivered = await bus.take_parked_signals("s2", "helper")
    assert [item["type"] for item in delivered] == ["signal_offer"]
    assert await bus.take_parked_signals("s2", "helper") == []


@pytest.mark.asyncio(loop_scope="session")
async def test_own_parked_signals_are_not_replayed_to_sender(fake_redis) -> None:
    await session_ws._relay_to_absent_peer("s3", "helpee", _offer("helpee"), limit=64)

    assert await bus.take_parked_signals("s3", "helpee") == []
    # Still waiting for the helper.
    assert len(await bus.take_parked_signals("s3", "helper")) == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_falls_back_to_local_buffer_without_redis(monkeypatch) -> None:
    def _broken():
        raise ConnectionError("redis down")

    monkeypatch.setattr(bus, "_redis", _broken)
    session_ws._pending_signals.clear()

    parked = await session_ws._relay_to_absent_peer("s4", "helpee", _offer("helpee"), limit=64)

    assert parked is True
    assert session_ws._pending_signals["s4"][0]["type"] == "signal_offer"
    session_ws._pending_signals.clear()
