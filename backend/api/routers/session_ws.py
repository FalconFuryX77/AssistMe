"""WebSocket endpoint for real-time session events.

This provides real-time notifications to session participants about
join/leave/disconnect/reconnect events, heartbeats, and session state
changes.  Full WebRTC signaling is handled in Phase 3.
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.session_service import SessionService
from core.database import async_session_factory
from core.security import decode_access_token
from models.session_participant import SessionParticipant
from models.user import User

router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory connection registry (per-process)
# ---------------------------------------------------------------------------

# Maps session_id → { user_id: WebSocket }
_connections: dict[str, dict[str, WebSocket]] = {}


async def _broadcast(session_id: str, message: dict, exclude_user: str | None = None) -> None:
    """Send a JSON message to all connected participants in a session."""
    room = _connections.get(session_id, {})
    disconnected = []
    for uid, ws in room.items():
        if uid == exclude_user:
            continue
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.append(uid)
    # Clean up broken connections
    for uid in disconnected:
        room.pop(uid, None)


async def _authenticate_ws(websocket: WebSocket) -> User | None:
    """Authenticate a WebSocket connection using the token query parameter.

    Expected URL: /ws/session/{session_id}?token=<JWT>
    """
    token = websocket.query_params.get("token")
    if not token:
        return None

    payload = decode_access_token(token)
    if payload is None:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

    return user


@router.websocket("/ws/session/{session_id}")
async def session_websocket(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint for real-time session communication.

    Authentication is via `?token=<JWT>` query parameter.

    Inbound messages (client → server):
        {"type": "heartbeat"}
        {"type": "leave"}

    Outbound messages (server → client):
        {"type": "user_joined", "user_id": "...", "role": "..."}
        {"type": "user_left", "user_id": "..."}
        {"type": "user_disconnected", "user_id": "..."}
        {"type": "user_reconnected", "user_id": "..."}
        {"type": "session_ended"}
        {"type": "heartbeat_ack"}
        {"type": "error", "detail": "..."}
    """
    # Authenticate
    user = await _authenticate_ws(websocket)
    if user is None:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    # Verify user is a participant
    async with async_session_factory() as db:
        result = await db.execute(
            select(SessionParticipant).where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.user_id == user.id,
            )
        )
        participant = result.scalar_one_or_none()

    if participant is None:
        await websocket.close(code=4003, reason="Not a session participant")
        return

    # Accept the connection
    await websocket.accept()

    # Register in connection pool
    if session_id not in _connections:
        _connections[session_id] = {}
    _connections[session_id][user.id] = websocket

    # If they were disconnected, mark them as reconnected
    if participant.status == "disconnected":
        async with async_session_factory() as db:
            result = await db.execute(
                select(SessionParticipant).where(
                    SessionParticipant.session_id == session_id,
                    SessionParticipant.user_id == user.id,
                )
            )
            p = result.scalar_one_or_none()
            if p:
                p.status = "connected"
                p.last_seen_at = datetime.now(timezone.utc)
                await db.commit()

        await _broadcast(
            session_id,
            {"type": "user_reconnected", "user_id": user.id},
            exclude_user=user.id,
        )
    else:
        # Notify others of the connection
        await _broadcast(
            session_id,
            {
                "type": "user_joined",
                "user_id": user.id,
                "role": participant.role,
            },
            exclude_user=user.id,
        )

    # Message loop
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "detail": "Invalid JSON"})
                continue

            msg_type = msg.get("type")

            if msg_type == "heartbeat":
                async with async_session_factory() as db:
                    await SessionService.heartbeat(session_id, user.id, db)
                await websocket.send_json({"type": "heartbeat_ack"})

            elif msg_type == "leave":
                async with async_session_factory() as db:
                    session = await SessionService.leave_session(
                        session_id, user.id, db
                    )
                await _broadcast(
                    session_id,
                    {"type": "user_left", "user_id": user.id},
                    exclude_user=user.id,
                )
                if session.status == "ended":
                    await _broadcast(session_id, {"type": "session_ended"})
                break  # Close the WebSocket after leaving

            else:
                await websocket.send_json(
                    {"type": "error", "detail": f"Unknown message type: {msg_type}"}
                )

    except WebSocketDisconnect:
        # Unexpected disconnect — mark as disconnected for recovery
        async with async_session_factory() as db:
            await SessionService.mark_disconnected(session_id, user.id, db)

        await _broadcast(
            session_id,
            {"type": "user_disconnected", "user_id": user.id},
            exclude_user=user.id,
        )

    finally:
        # Remove from connection pool
        room = _connections.get(session_id, {})
        room.pop(user.id, None)
        if not room:
            _connections.pop(session_id, None)
