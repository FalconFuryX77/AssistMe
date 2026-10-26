"""Per-device WebSocket channel — the ring channel.

A persistent connection every logged-in device keeps open regardless of
sessions. Incoming help requests, acceptances and denials are pushed here so
the helper's phone rings even when nobody is inside any session. This is what
removes the session-code dance from the product.
"""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from core.database import async_session_factory
from core.realtime_bus import listen, publish
from core.security import decode_access_token
from models.user import User

router = APIRouter()

# user_id → list of live sockets (a user may have the app on several devices)
_device_connections: dict[str, list[WebSocket]] = {}
_device_bus_tasks: dict[str, asyncio.Task] = {}


def is_user_online(user_id: str) -> bool:
    """Whether the user currently has any live ring-channel socket."""
    return bool(_device_connections.get(user_id))


async def push_to_user(user_id: str, payload: dict) -> bool:
    """Push a JSON event to every live socket of a user.

    Returns True if at least one socket received it.
    """
    sockets = _device_connections.get(user_id, [])
    delivered = False
    dead: list[WebSocket] = []
    for ws in sockets:
        try:
            await ws.send_json(payload)
            delivered = True
        except Exception:
            dead.append(ws)
    for ws in dead:
        _drop(user_id, ws)
    await publish(f"assistme:user:{user_id}", {"payload": payload})
    return delivered


async def _listen_user_bus(user_id: str) -> None:
    async def deliver(event: dict) -> None:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return
        for ws in list(_device_connections.get(user_id, [])):
            try:
                await ws.send_json(payload)
            except Exception:
                _drop(user_id, ws)

    await listen(f"assistme:user:{user_id}", deliver)


def _ensure_user_bus(user_id: str) -> None:
    task = _device_bus_tasks.get(user_id)
    if task is None or task.done():
        _device_bus_tasks[user_id] = asyncio.create_task(_listen_user_bus(user_id))


def _drop(user_id: str, ws: WebSocket) -> None:
    sockets = _device_connections.get(user_id)
    if not sockets:
        return
    try:
        sockets.remove(ws)
    except ValueError:
        pass
    if not sockets:
        _device_connections.pop(user_id, None)
        task = _device_bus_tasks.pop(user_id, None)
        if task:
            task.cancel()


@router.websocket("/ws/device")
async def device_channel(websocket: WebSocket) -> None:
    """Persistent ring channel, authenticated by a bearer request header."""
    user_id = await _authenticated_user_id(websocket)
    if not user_id:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    await websocket.accept()
    _device_connections.setdefault(user_id, []).append(websocket)
    _ensure_user_bus(user_id)

    try:
        await websocket.send_json({"type": "channel_ready", "user_id": user_id})
        while True:
            raw = await websocket.receive_text()
            # Minimal client protocol; heartbeat keeps intermediaries happy.
            if raw == "heartbeat" or '"heartbeat"' in raw.replace(" ", ""):
                await websocket.send_json({"type": "heartbeat_ack"})
    except WebSocketDisconnect:
        pass
    finally:
        _drop(user_id, websocket)


async def _authenticated_user_id(websocket: WebSocket) -> str | None:
    """Return the active account bound to the request bearer token."""
    authorization = websocket.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None

    try:
        payload = decode_access_token(token.strip())
    except Exception:
        payload = None
    user_id = (payload or {}).get("sub") if isinstance(payload, dict) else None
    if not isinstance(user_id, str) or not user_id:
        return None

    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    return str(user.id)
