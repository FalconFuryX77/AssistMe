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
