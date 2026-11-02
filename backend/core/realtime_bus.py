"""Small Redis pub/sub bridge for WebSocket fan-out across API workers."""

import asyncio
import json
import os
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis

from core.config import settings

_origin = f"{os.getpid()}-{id(object())}"
_publisher: Redis | None = None


def _redis() -> Redis:
    global _publisher
    if _publisher is None:
        _publisher = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _publisher


async def publish(channel: str, payload: dict) -> None:
    """Best-effort publish; local WebSockets remain the fallback."""
    try:
        await _redis().publish(
            channel,
            json.dumps({"origin": _origin, "payload": payload}),
        )
    except Exception:
        # Redis is an availability enhancement for multi-worker fan-out. A
        # single-worker development process still works without it.
        return


async def listen(
    channel: str,
    callback: Callable[[dict], Awaitable[None]],
) -> None:
    """Listen until cancelled, reconnecting if Redis briefly disappears."""
    while True:
        pubsub = None
        try:
            client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
            pubsub = client.pubsub()
            await pubsub.subscribe(channel)
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if not message or not message.get("data"):
                    continue
                envelope = json.loads(message["data"])
                if envelope.get("origin") == _origin:
                    continue
                payload = envelope.get("payload")
                if isinstance(payload, dict):
                    await callback(payload)
        except asyncio.CancelledError:
            return
        except Exception:
            await asyncio.sleep(2)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.close()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Cross-worker presence and parked signaling
#
# The API runs several workers and each only knows its own WebSockets. A
# signaling message for a peer that is not on this worker must either be
# published (the peer is connected to another worker) or parked where any
# worker can replay it (the peer has not connected yet). Both live in Redis.
# Every function returns None when Redis is unavailable so callers can fall
# back to the per-worker behaviour.
# ---------------------------------------------------------------------------

_PRESENCE_TTL_SECONDS = 6 * 60 * 60
_PARKED_TTL_SECONDS = 120
_PARKED_MAX = 64


def _presence_key(session_id: str) -> str:
    # A hash of user id -> id of that user's latest session socket. (A new
    # key name: earlier builds stored a plain set under "presence".)
    return f"assistme:presence2:{session_id}"


def _parked_key(session_id: str) -> str:
    return f"assistme:parked:{session_id}"


# Delete the field only if it still names this connection.
_RELEASE_IF_CURRENT = """
if redis.call('HGET', KEYS[1], ARGV[1]) == ARGV[2] then
  redis.call('HDEL', KEYS[1], ARGV[1])
  return 1
end
return 0
"""


async def presence_add(
    session_id: str, user_id: str, connection_id: str
) -> bool | None:
    """Record ``connection_id`` as this user's latest session socket."""
    try:
        redis = _redis()
        await redis.hset(_presence_key(session_id), user_id, connection_id)
        await redis.expire(_presence_key(session_id), _PRESENCE_TTL_SECONDS)
        return True
    except Exception:
        return None


async def presence_release(
    session_id: str, user_id: str, connection_id: str
) -> bool | None:
    """Forget this socket if it is still the user's latest one.

    Returns False when a newer socket (often on another worker, after a
    Wi-Fi <-> mobile data switch) has already taken over: the close being
    handled is stale and must not be reported as a disconnect.
    """
    try:
        removed = await _redis().eval(
            _RELEASE_IF_CURRENT, 1, _presence_key(session_id), user_id, connection_id
        )
        return int(removed) == 1
    except Exception:
        return None


async def others_present(session_id: str, user_id: str) -> bool | None:
    """True if another participant holds a session socket on any worker."""
    try:
        members = await _redis().hkeys(_presence_key(session_id))
        return any(member != user_id for member in members)
    except Exception:
        return None


async def park_signal(session_id: str, payload: dict) -> bool | None:
    """Keep a signal for a peer that has not connected anywhere yet."""
    try:
        redis = _redis()
        key = _parked_key(session_id)
        await redis.rpush(key, json.dumps(payload))
        await redis.ltrim(key, -_PARKED_MAX, -1)
        await redis.expire(key, _PARKED_TTL_SECONDS)
        return True
    except Exception:
        return None


async def take_parked_signals(session_id: str, user_id: str) -> list[dict] | None:
    """Remove and return the parked signals another participant sent."""
    try:
        redis = _redis()
        key = _parked_key(session_id)
        raw_items = await redis.lrange(key, 0, -1)
        if not raw_items:
            return []
        await redis.delete(key)
        mine: list[str] = []
        theirs: list[dict] = []
        for raw in raw_items:
            try:
                item = json.loads(raw)
            except ValueError:
                continue
            if item.get("sender_user_id") == user_id:
                mine.append(raw)
            else:
                theirs.append(item)
        if mine:
            # Our own signals still wait for the other participant.
            await redis.rpush(key, *mine)
            await redis.expire(key, _PARKED_TTL_SECONDS)
        return theirs
    except Exception:
        return None
