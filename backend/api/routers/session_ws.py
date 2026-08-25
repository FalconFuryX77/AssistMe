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

            # AssistMe is intentionally a two-person screen/voice session.
            # Ignore legacy chat, file, group, policy, recording, and
            # zeroization messages instead of forwarding them to a phone.
            allowed_types = {
                "heartbeat", "leave", "signal_offer", "signal_answer",
                "signal_ice_candidate", "screen_share_start", "screen_share_stop",
                "audio_mute_toggle", "draw_stroke", "draw_clear",
                "assistance_requested", "assistance_request_responded",
                "escalation_requested", "escalation_responded",
            }
            if msg_type not in allowed_types:
                await websocket.send_json({"type": "unsupported_message"})
                continue

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

            elif msg_type in ("signal_offer", "signal_answer", "signal_ice_candidate"):
                # Forward WebRTC signaling payload to target user or broadcast
                target_user_id = msg.get("target_user_id")
                payload = {
                    "type": msg_type,
                    "sender_user_id": user.id,
                    "sdp": msg.get("sdp"),
                    "candidate": msg.get("candidate"),
                }
                if target_user_id:
                    room = _connections.get(session_id, {})
                    target_ws = room.get(target_user_id)
                    if target_ws:
                        await target_ws.send_json(payload)
                    else:
                        await websocket.send_json(
                            {"type": "error", "detail": "Target user not connected"}
                        )
                else:
                    await _broadcast(session_id, payload, exclude_user=user.id)

            elif msg_type in (
                "screen_share_start",
                "screen_share_stop",
                "screen_share_orientation",
                "screen_share_security_event",
            ):
                # Broadcast screen sharing state / security event to room participants
                payload = {
                    "type": msg_type,
                    "sender_user_id": user.id,
                    "platform": msg.get("platform"),
                    "orientation": msg.get("orientation"),
                    "event_type": msg.get("event_type"),
                    "detail": msg.get("detail"),
                    "reason": msg.get("reason"),
                }
                await _broadcast(session_id, payload, exclude_user=user.id)

            elif msg_type in (
                "audio_call_start",
                "audio_call_stop",
                "audio_mute_toggle",
                "audio_route_change",
                "audio_degradation_report",
            ):
                # Broadcast voice communication events to room participants
                payload = {
                    "type": msg_type,
                    "sender_user_id": user.id,
                    "is_muted": msg.get("is_muted"),
                    "audio_route": msg.get("audio_route"),
                    "quality_level": msg.get("quality_level"),
                    "packet_loss": msg.get("packet_loss"),
                }
                await _broadcast(session_id, payload, exclude_user=user.id)

            elif msg_type in (
                "remote_control_grant",
                "remote_control_revoke",
                "remote_control_input",
            ):
                # Broadcast or forward remote control gesture/key events
                payload = {
                    "type": msg_type,
                    "sender_user_id": user.id,
                    "platform": msg.get("platform"),
                    "event": msg.get("event"),
                }
                await _broadcast(session_id, payload, exclude_user=user.id)

            elif msg_type in (
                "streaming_adapted",
                "network_metrics_reported",
            ):
                # Broadcast adaptive video resolution / FPS / network metrics updates
                payload = {
                    "type": msg_type,
                    "sender_user_id": user.id,
                    "video_resolution": msg.get("video_resolution"),
                    "video_bitrate_kbps": msg.get("video_bitrate_kbps"),
                    "video_fps": msg.get("video_fps"),
                    "rtt_ms": msg.get("rtt_ms"),
                    "packet_loss_percent": msg.get("packet_loss_percent"),
                }
                await _broadcast(session_id, payload, exclude_user=user.id)

            elif msg_type in (
                "e2ee_key_exchange",
                "e2ee_key_rotate",
                "e2ee_verification_status",
            ):
                # Forward Signal Double Ratchet / Insertable Streams key exchange & safety number fingerprint verification
                payload = {
                    "type": msg_type,
                    "sender_user_id": user.id,
                    "identity_key": msg.get("identity_key"),
                    "signed_prekey": msg.get("signed_prekey"),
                    "ephemeral_key": msg.get("ephemeral_key"),
                    "fingerprint": msg.get("fingerprint"),
                    "is_mitm_verified": msg.get("is_mitm_verified"),
                }
                await _broadcast(session_id, payload, exclude_user=user.id)

            elif msg_type in (
                "recording_consent_updated",
                "recording_started",
                "recording_stopped",
            ):
                # Broadcast session recording consent and status events
                payload = {
                    "type": msg_type,
                    "sender_user_id": user.id,
                    "consent_granted": msg.get("consent_granted"),
                    "recording_scope": msg.get("recording_scope"),
                    "recording_url": msg.get("recording_url"),
                }
                await _broadcast(session_id, payload, exclude_user=user.id)

            elif msg_type in (
                "participant_invited",
                "participant_role_updated",
                "active_speaker_changed",
            ):
                # Broadcast multi-party role changes, participant invitations, and active speaker signals
                payload = {
                    "type": msg_type,
                    "sender_user_id": user.id,
                    "target_user_id": msg.get("target_user_id"),
                    "role": msg.get("role"),
                    "active_speaker_user_id": msg.get("active_speaker_user_id"),
                    "audio_level_db": msg.get("audio_level_db"),
                }
                await _broadcast(session_id, payload, exclude_user=user.id)

            elif msg_type in (
                "chat_message_received",
                "file_transfer_initiated",
                "file_chunk_received",
                "file_transfer_completed",
            ):
                # Broadcast real-time text chat messages, E2EE payloads, and chunked file transfer signals
                payload = {
                    "type": msg_type,
                    "sender_user_id": user.id,
                    "message_id": msg.get("message_id"),
                    "content": msg.get("content"),
                    "is_encrypted": msg.get("is_encrypted"),
                    "encrypted_payload": msg.get("encrypted_payload"),
                    "file_transfer_id": msg.get("file_transfer_id"),
                    "filename": msg.get("filename"),
                    "chunk_index": msg.get("chunk_index"),
                    "download_url": msg.get("download_url"),
                }
                await _broadcast(session_id, payload, exclude_user=user.id)

            elif msg_type in (
                "ice_restart_requested",
                "security_zeroized",
            ):
                # Broadcast WebRTC ICE restart requests and zeroization security events
                payload = {
                    "type": msg_type,
                    "sender_user_id": user.id,
                    "reason": msg.get("reason"),
                    "ufrag": msg.get("ufrag"),
                    "pwd": msg.get("pwd"),
                    "zeroized": msg.get("zeroized"),
                }
                await _broadcast(session_id, payload, exclude_user=user.id)

            elif msg_type == "context_reported":
                # Broadcast the helpee's updated device/session context snapshot
                payload = {
                    "type": msg_type,
                    "sender_user_id": user.id,
                    "platform": msg.get("platform"),
                    "os_version": msg.get("os_version"),
                    "foreground_app": msg.get("foreground_app"),
                    "foreground_app_category": msg.get("foreground_app_category"),
                    "is_sensitive_app": msg.get("is_sensitive_app"),
                    "accessibility_enabled": msg.get("accessibility_enabled"),
                    "is_screen_sharing": msg.get("is_screen_sharing"),
                    "is_flag_secure_active": msg.get("is_flag_secure_active"),
                }
                await _broadcast(session_id, payload, exclude_user=user.id)

            elif msg_type == "policy_updated":
                # Broadcast adaptive policy decision changes (risk / mode)
                payload = {
                    "type": msg_type,
                    "sender_user_id": user.id,
                    "risk_level": msg.get("risk_level"),
                    "assistance_mode": msg.get("assistance_mode"),
                    "negotiated_capabilities": msg.get("negotiated_capabilities"),
                    "consent_verified": msg.get("consent_verified"),
                }
                await _broadcast(session_id, payload, exclude_user=user.id)

            elif msg_type in (
                "task_recorded",
                "suggestions_updated",
                "preferred_mode_updated",
            ):
                # Broadcast intelligent-assistance learning / suggestion updates
                payload = {
                    "type": msg_type,
                    "sender_user_id": user.id,
                    "action": msg.get("action"),
                    "occurrence_count": msg.get("occurrence_count"),
                    "preferred_mode": msg.get("preferred_mode"),
                }
                await _broadcast(session_id, payload, exclude_user=user.id)

            elif msg_type in (
                "assistance_requested",
                "assistance_request_responded",
                "escalation_requested",
                "escalation_responded",
            ):
                # Broadcast the one-click help / escalation flow events
                payload = {
                    "type": msg_type,
                    "sender_user_id": user.id,
                    "request_id": msg.get("request_id"),
                    "escalation_id": msg.get("escalation_id"),
                    "helper_user_id": msg.get("helper_user_id"),
                    "helpee_user_id": msg.get("helpee_user_id"),
                    "status": msg.get("status"),
                    "target_capabilities": msg.get("target_capabilities"),
                    "disclaimer_text": msg.get("disclaimer_text"),
                }
                await _broadcast(session_id, payload, exclude_user=user.id)

            elif msg_type in ("draw_stroke", "draw_clear"):
                # Drawing is the default, least-privilege guidance layer.
                # It never grants touch control and is relayed to both phones.
                await _broadcast(
                    session_id,
                    {
                        "type": msg_type,
                        "sender_user_id": user.id,
                        "points": msg.get("points"),
                    },
                    exclude_user=user.id,
                )

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
