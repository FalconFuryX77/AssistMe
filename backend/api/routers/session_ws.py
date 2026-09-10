"""WebSocket endpoint for real-time session events.

This provides real-time notifications to session participants about
join/leave/disconnect/reconnect events, heartbeats, and session state
changes.  Full WebRTC signaling is handled in Phase 3.
"""

import json
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.session_service import SessionService
from api.schemas.remote_control import RemoteControlInputEvent
from api.services.remote_control_service import RemoteControlService
from core.database import async_session_factory
from core.realtime_bus import listen, publish
from core.security import decode_access_token
from models.session import Session
from models.session_participant import SessionParticipant
from models.user import User

router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory connection registry (per-process)
# ---------------------------------------------------------------------------

# Maps session_id → { user_id: WebSocket }
_connections: dict[str, dict[str, WebSocket]] = {}
_pending_signals: dict[str, list[dict]] = {}
_disconnect_tasks: dict[tuple[str, str], asyncio.Task] = {}
_DISCONNECT_GRACE_SECONDS = 300
_session_bus_tasks: dict[str, asyncio.Task] = {}


async def _broadcast(
    session_id: str,
    message: dict,
    exclude_user: str | None = None,
    *,
    publish_globally: bool = True,
) -> None:
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
    if publish_globally:
        await publish(
            f"assistme:session:{session_id}",
            {"message": message, "exclude_user": exclude_user},
        )


async def _listen_session_bus(session_id: str) -> None:
    async def deliver(payload: dict) -> None:
        message = payload.get("message")
        if isinstance(message, dict):
            await _broadcast(
                session_id,
                message,
                payload.get("exclude_user"),
                publish_globally=False,
            )

    await listen(f"assistme:session:{session_id}", deliver)


def _ensure_session_bus(session_id: str) -> None:
    task = _session_bus_tasks.get(session_id)
    if task is None or task.done():
        _session_bus_tasks[session_id] = asyncio.create_task(
            _listen_session_bus(session_id)
        )


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

    # Verify that the room is still live and that this participant has not
    # explicitly left.  This prevents a stale token from reopening a finished
    # call and receiving buffered signaling frames.
    async with async_session_factory() as db:
        result = await db.execute(
            select(Session, SessionParticipant)
            .join(Session, Session.id == SessionParticipant.session_id)
            .where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.user_id == user.id,
            )
        )
        row = result.one_or_none()

    if row is None:
        await websocket.close(code=4003, reason="Not a session participant")
        return

    session, participant = row
    if session.status == "ended":
        await websocket.close(code=4004, reason="Session has ended")
        return
    if participant.status == "left":
        await websocket.close(code=4003, reason="Not a session participant")
        return

    # Accept the connection
    await websocket.accept()

    # Register in connection pool
    if session_id not in _connections:
        _connections[session_id] = {}
    _connections[session_id][user.id] = websocket
    print(f"[WS-DEBUG] User {user.id} ({user.display_name}) connected to session {session_id}. Room members: {list(_connections.get(session_id, {}).keys())}")
    print(f"[WS-DEBUG] Pending signals for session: {len(_pending_signals.get(session_id, []))}")

    _ensure_session_bus(session_id)
    pending_disconnect = _disconnect_tasks.pop((session_id, user.id), None)
    if pending_disconnect:
        pending_disconnect.cancel()

    # A caller may publish its offer before the other phone finishes opening
    # the session socket. Replay buffered signaling immediately on connect.
    pending_signals = _pending_signals.get(session_id, [])
    remaining_signals = []
    for pending in pending_signals:
        # Never replay a participant's own buffered signal back to them after
        # a transient reconnect.
        if pending.get("sender_user_id") == user.id:
            remaining_signals.append(pending)
            continue
        try:
            await websocket.send_json(pending)
        except Exception:
            remaining_signals.append(pending)
    if remaining_signals:
        _pending_signals[session_id] = remaining_signals
    else:
        _pending_signals.pop(session_id, None)

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
                "signal_ice_candidate", "request_offer", "screen_share_start", "screen_share_stop",
                "screen_share_orientation", "screen_share_security_event",
                "audio_call_start", "audio_call_stop", "audio_mute_toggle",
                "audio_route_change", "audio_degradation_report",
                "remote_control_input",
                "draw_preview", "draw_stroke", "draw_erase", "draw_undo", "draw_redo", "draw_clear",
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
                room = _connections.get(session_id, {})
                print(f"[WS-DEBUG] {msg_type} from user {user.id}. Room: {list(room.keys())}")
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
                        queue = _pending_signals.setdefault(session_id, [])
                        if len(queue) < 32:
                            queue.append(payload)
                    await publish(
                        f"assistme:session:{session_id}",
                        {"message": payload, "exclude_user": user.id},
                    )
                else:
                    # The mobile clients intentionally use room signaling. If
                    # the peer is between WebSocket connections during a
                    # reconnect, a plain broadcast would silently drop the
                    # fresh offer/ICE and leave the viewport blank. Buffer the
                    # signal until another participant connects; normal live
                    # signaling remains an immediate broadcast.
                    room = _connections.get(session_id, {})
                    recipients = [uid for uid in room if uid != user.id]
                    if recipients:
                        await _broadcast(session_id, payload, exclude_user=user.id)
                    else:
                        queue = _pending_signals.setdefault(session_id, [])
                        if len(queue) < 64:
                            queue.append(payload)

            elif msg_type == "request_offer":
                await _broadcast(session_id, {"type": "request_offer", "sender_user_id": user.id}, exclude_user=user.id)

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

            elif msg_type == "remote_control_input":
                # Block helper from tapping helpee's panic/STOP controls (top ~8% of screen where
                # AssistMeAnnotationOverlayService places its dock). Control must stay with old man.
                try:
                    raw = msg.get("event") or {}
                    ny = raw.get("normalized_y")
                    ny_end = raw.get("normalized_end_y")
                    if isinstance(ny, (int, float)) and 0 <= ny < 0.08:
                        await websocket.send_json({"type": "error", "detail": "Control blocked: helpee controls area"})
                        continue
                    if isinstance(ny_end, (int, float)) and 0 <= ny_end < 0.08:
                        await websocket.send_json({"type": "error", "detail": "Control blocked: helpee controls area"})
                        continue
                except Exception:
                    pass
                # The WebSocket is a transport optimization, not a second
                # authorization path. Apply the same active-session,
                # helper-role, and helpee-granted checks as REST input.
                try:
                    input_event = RemoteControlInputEvent.model_validate(
                        msg.get("event") or {}
                    )
                    async with async_session_factory() as db:
                        dispatched = await RemoteControlService.dispatch_input_event(
                            session_id=session_id,
                            user_id=user.id,
                            input_event=input_event,
                            db=db,
                        )
                except HTTPException as exc:
                    await websocket.send_json(
                        {"type": "error", "detail": exc.detail}
                    )
                    continue
                except ValueError as exc:
                    await websocket.send_json(
                        {"type": "error", "detail": str(exc)}
                    )
                    continue

                payload = {
                    "type": msg_type,
                    "sender_user_id": user.id,
                    "platform": dispatched["platform"],
                    "event": dispatched["event"],
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

            elif msg_type in (
                "draw_preview", "draw_stroke", "draw_erase", "draw_undo", "draw_redo", "draw_clear"
            ):
                # Drawing is the default, least-privilege guidance layer.
                # Validate and bound payload to prevent memory/CPU exhaustion.
                raw_points = msg.get("points")
                sanitized_points = None
                if isinstance(raw_points, list):
                    sanitized_points = []
                    for pt in raw_points[:128]:
                        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                            try:
                                px = max(0.0, min(1.0, float(pt[0])))
                                py = max(0.0, min(1.0, float(pt[1])))
                                sanitized_points.append([px, py])
                            except (ValueError, TypeError):
                                pass
                        elif isinstance(pt, dict) and "x" in pt and "y" in pt:
                            try:
                                px = max(0.0, min(1.0, float(pt["x"])))
                                py = max(0.0, min(1.0, float(pt["y"])))
                                sanitized_points.append({"x": px, "y": py})
                            except (ValueError, TypeError):
                                pass

                raw_point = msg.get("point")
                sanitized_point = None
                if isinstance(raw_point, (list, tuple)) and len(raw_point) >= 2:
                    try:
                        sanitized_point = [
                            max(0.0, min(1.0, float(raw_point[0]))),
                            max(0.0, min(1.0, float(raw_point[1]))),
                        ]
                    except (ValueError, TypeError):
                        pass

                raw_width = msg.get("width")
                sanitized_width = 4.0
                if isinstance(raw_width, (int, float)):
                    sanitized_width = max(1.0, min(50.0, float(raw_width)))

                raw_color = msg.get("color")
                sanitized_color = raw_color if isinstance(raw_color, (int, float)) else str(raw_color or "#FF0000")[:32]

                await _broadcast(
                    session_id,
                    {
                        "type": msg_type,
                        "sender_user_id": user.id,
                        "points": sanitized_points,
                        "point": sanitized_point,
                        "color": sanitized_color,
                        "width": sanitized_width,
                    },
                    exclude_user=user.id,
                )

            else:
                await websocket.send_json(
                    {"type": "error", "detail": f"Unknown message type: {msg_type}"}
                )

    except (WebSocketDisconnect, Exception):
        # Android may briefly suspend this socket while the MediaProjection
        # consent activity is on screen. Keep the session alive while the
        # client reconnects; only a sustained disconnect ends the call.
        try:
            async with async_session_factory() as db:
                await SessionService.mark_disconnected(session_id, user.id, db)

            await _broadcast(
                session_id,
                {"type": "user_disconnected", "user_id": user.id, "reconnecting": True},
                exclude_user=user.id,
            )
        except Exception:
            pass
        task = asyncio.create_task(_end_after_disconnect(session_id, user.id))
        _disconnect_tasks[(session_id, user.id)] = task

    finally:
        # Remove from connection pool
        room = _connections.get(session_id, {})
        room.pop(user.id, None)
        if not room:
            _connections.pop(session_id, None)
            _pending_signals.pop(session_id, None)
            bus_task = _session_bus_tasks.pop(session_id, None)
            if bus_task:
                bus_task.cancel()


async def _end_after_disconnect(session_id: str, user_id: str) -> None:
    """End the call only after the reconnect grace window expires."""
    try:
        await asyncio.sleep(_DISCONNECT_GRACE_SECONDS)
        async with async_session_factory() as db:
            session = await SessionService.terminate_on_disconnect(session_id, user_id, db)
        if session is not None:
            await _broadcast(
                session_id,
                {"type": "session_ended", "reason": "participant_disconnected", "user_id": user_id},
                exclude_user=user_id,
            )
    except asyncio.CancelledError:
        pass
    finally:
        _disconnect_tasks.pop((session_id, user_id), None)
