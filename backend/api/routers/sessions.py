"""Session management REST API routes."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas.sessions import (
    SessionCreateRequest,
    SessionJoinRequest,
    SessionListItem,
    SessionRecoverRequest,
    SessionResponse,
    ParticipantResponse,
)
from api.schemas.screen_share import (
    ScreenShareOrientationRequest,
    ScreenShareSecurityEventRequest,
    ScreenShareStartRequest,
    ScreenShareStatusResponse,
    ScreenShareStopRequest,
)
from api.schemas.remote_control import (
    RemoteControlGrantRequest,
    RemoteControlInputEvent,
    RemoteControlStatusResponse,
)
from api.schemas.voice import (
    AudioCallStartRequest,
    AudioDegradationReportRequest,
    AudioMuteToggleRequest,
    AudioRouteChangeRequest,
    AudioStatusResponse,
)
from api.schemas.webrtc import ICEServersResponse
from api.services.remote_control_service import RemoteControlService
from api.services.screen_share_service import ScreenShareService
from api.services.session_service import SessionService
from api.services.voice_service import VoiceService
from api.services.webrtc_service import WebRTCService
from core.database import get_db
from models.session import Session
from models.user import User

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _enrich_session(session: Session) -> dict:
    """Convert a Session ORM object to a response dict with enriched participants."""
    return {
        "id": session.id,
        "creator_id": session.creator_id,
        "status": session.status,
        "title": session.title,
        "session_code": session.session_code,
        "timeout_minutes": session.timeout_minutes,
        "remote_control_granted": session.remote_control_granted,
        "remote_control_granted_at": session.remote_control_granted_at,
        "remote_control_platform": session.remote_control_platform,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "ended_at": session.ended_at,
        "participants": [
            {
                "id": p.id,
                "user_id": p.user_id,
                "role": p.role,
                "status": p.status,
                "joined_at": p.joined_at,
                "last_seen_at": p.last_seen_at,
                "is_screen_sharing": p.is_screen_sharing,
                "screen_share_platform": p.screen_share_platform,
                "is_flag_secure_active": p.is_flag_secure_active,
                "screen_orientation": p.screen_orientation,
                "is_in_audio_call": p.is_in_audio_call,
                "is_audio_muted": p.is_audio_muted,
                "audio_route": p.audio_route,
                "audio_quality": p.audio_quality,
            }
            for p in session.participants
        ],
    }


@router.post(
    "/",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    payload: SessionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new assistance session."""
    session = await SessionService.create_session(
        creator_id=current_user.id,
        title=payload.title,
        timeout_minutes=payload.timeout_minutes,
        db=db,
    )
    return _enrich_session(session)


@router.post("/join", response_model=SessionResponse)
async def join_session(
    payload: SessionJoinRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Join a session by its code."""
    session = await SessionService.join_session(
        session_code=payload.session_code,
        user_id=current_user.id,
        db=db,
    )
    return _enrich_session(session)


@router.get("/", response_model=list[SessionListItem])
async def list_sessions(
    status_filter: str | None = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List sessions the current user is involved in."""
    return await SessionService.list_sessions(
        user_id=current_user.id,
        status_filter=status_filter,
        db=db,
    )


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get details of a specific session."""
    session = await SessionService.get_session(
        session_id=session_id,
        user_id=current_user.id,
        db=db,
    )
    return _enrich_session(session)


@router.get("/{session_id}/ice-servers", response_model=ICEServersResponse)
async def get_ice_servers(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ICEServersResponse:
    """Get WebRTC RTCIceServer configuration (STUN/TURN) for this session."""
    # Verify participant access
    await SessionService.get_session(
        session_id=session_id,
        user_id=current_user.id,
        db=db,
    )
    return WebRTCService.get_ice_servers()


@router.post("/{session_id}/leave", response_model=SessionResponse)
async def leave_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Leave a session."""
    session = await SessionService.leave_session(
        session_id=session_id,
        user_id=current_user.id,
        db=db,
    )
    return _enrich_session(session)


@router.post("/{session_id}/end", response_model=SessionResponse)
async def end_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """End a session (creator only)."""
    session = await SessionService.end_session(
        session_id=session_id,
        user_id=current_user.id,
        db=db,
    )
    return _enrich_session(session)


@router.post("/recover", response_model=SessionResponse)
async def recover_session(
    payload: SessionRecoverRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Recover a session after disconnection."""
    session = await SessionService.recover_session(
        session_id=payload.session_id,
        user_id=current_user.id,
        db=db,
    )
    return _enrich_session(session)


@router.post("/{session_id}/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
async def heartbeat(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Send a keep-alive heartbeat for the session."""
    await SessionService.heartbeat(
        session_id=session_id,
        user_id=current_user.id,
        db=db,
    )


# ---------------------------------------------------------------------------
# Screen Sharing Routes
# ---------------------------------------------------------------------------


@router.post("/{session_id}/screen-share/start", response_model=ScreenShareStatusResponse)
async def start_screen_share(
    session_id: str,
    payload: ScreenShareStartRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Start screen sharing stream."""
    participant = await ScreenShareService.start_screen_share(
        session_id=session_id,
        user_id=current_user.id,
        platform=payload.platform,
        orientation=payload.orientation,
        db=db,
    )
    return {
        "is_screen_sharing": participant.is_screen_sharing,
        "platform": participant.screen_share_platform,
        "is_flag_secure_active": participant.is_flag_secure_active,
        "screen_orientation": participant.screen_orientation,
        "participant_user_id": participant.user_id,
    }


@router.post("/{session_id}/screen-share/stop", response_model=ScreenShareStatusResponse)
async def stop_screen_share(
    session_id: str,
    payload: ScreenShareStopRequest = ScreenShareStopRequest(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Stop screen sharing stream."""
    participant = await ScreenShareService.stop_screen_share(
        session_id=session_id,
        user_id=current_user.id,
        reason=payload.reason,
        db=db,
    )
    return {
        "is_screen_sharing": participant.is_screen_sharing,
        "platform": participant.screen_share_platform,
        "is_flag_secure_active": participant.is_flag_secure_active,
        "screen_orientation": participant.screen_orientation,
        "participant_user_id": participant.user_id,
    }


@router.post("/{session_id}/screen-share/orientation", response_model=ScreenShareStatusResponse)
async def update_screen_share_orientation(
    session_id: str,
    payload: ScreenShareOrientationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update screen share orientation (portrait/landscape)."""
    participant = await ScreenShareService.update_orientation(
        session_id=session_id,
        user_id=current_user.id,
        orientation=payload.orientation,
        db=db,
    )
    return {
        "is_screen_sharing": participant.is_screen_sharing,
        "platform": participant.screen_share_platform,
        "is_flag_secure_active": participant.is_flag_secure_active,
        "screen_orientation": participant.screen_orientation,
        "participant_user_id": participant.user_id,
    }


@router.post("/{session_id}/screen-share/security-event", response_model=ScreenShareStatusResponse)
async def report_screen_share_security_event(
    session_id: str,
    payload: ScreenShareSecurityEventRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Report FLAG_SECURE, protected app, or backgrounding events."""
    participant = await ScreenShareService.handle_security_event(
        session_id=session_id,
        user_id=current_user.id,
        event_type=payload.event_type,
        detail=payload.detail,
        db=db,
    )
    return {
        "is_screen_sharing": participant.is_screen_sharing,
        "platform": participant.screen_share_platform,
        "is_flag_secure_active": participant.is_flag_secure_active,
        "screen_orientation": participant.screen_orientation,
        "participant_user_id": participant.user_id,
    }


@router.get("/{session_id}/screen-share/status", response_model=ScreenShareStatusResponse)
async def get_screen_share_status(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get active screen share status for a session."""
    return await ScreenShareService.get_status(
        session_id=session_id,
        user_id=current_user.id,
        db=db,
    )


# ---------------------------------------------------------------------------
# Voice Communication Routes (Phase 5)
# ---------------------------------------------------------------------------


@router.post("/{session_id}/audio/start", response_model=AudioStatusResponse)
async def start_audio_call(
    session_id: str,
    payload: AudioCallStartRequest = AudioCallStartRequest(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Start audio call participation in session."""
    participant = await VoiceService.start_audio_call(
        session_id=session_id,
        user_id=current_user.id,
        is_muted=payload.is_muted,
        audio_route=payload.audio_route,
        db=db,
    )
    return {
        "is_in_audio_call": participant.is_in_audio_call,
        "is_audio_muted": participant.is_audio_muted,
        "audio_route": participant.audio_route,
        "audio_quality": participant.audio_quality,
        "participant_user_id": participant.user_id,
    }


@router.post("/{session_id}/audio/stop", response_model=AudioStatusResponse)
async def stop_audio_call(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Stop audio call participation."""
    participant = await VoiceService.stop_audio_call(
        session_id=session_id,
        user_id=current_user.id,
        db=db,
    )
    return {
        "is_in_audio_call": participant.is_in_audio_call,
        "is_audio_muted": participant.is_audio_muted,
        "audio_route": participant.audio_route,
        "audio_quality": participant.audio_quality,
        "participant_user_id": participant.user_id,
    }


@router.post("/{session_id}/audio/mute", response_model=AudioStatusResponse)
async def toggle_audio_mute(
    session_id: str,
    payload: AudioMuteToggleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Toggle audio mute state (mute/unmute)."""
    participant = await VoiceService.toggle_mute(
        session_id=session_id,
        user_id=current_user.id,
        is_muted=payload.is_muted,
        db=db,
    )
    return {
        "is_in_audio_call": participant.is_in_audio_call,
        "is_audio_muted": participant.is_audio_muted,
        "audio_route": participant.audio_route,
        "audio_quality": participant.audio_quality,
        "participant_user_id": participant.user_id,
    }


@router.post("/{session_id}/audio/route", response_model=AudioStatusResponse)
async def change_audio_route(
    session_id: str,
    payload: AudioRouteChangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Change audio output route (speaker, earpiece, bluetooth, headset)."""
    participant = await VoiceService.change_audio_route(
        session_id=session_id,
        user_id=current_user.id,
        audio_route=payload.audio_route,
        db=db,
    )
    return {
        "is_in_audio_call": participant.is_in_audio_call,
        "is_audio_muted": participant.is_audio_muted,
        "audio_route": participant.audio_route,
        "audio_quality": participant.audio_quality,
        "participant_user_id": participant.user_id,
    }


@router.post("/{session_id}/audio/degradation", response_model=AudioStatusResponse)
async def report_audio_degradation(
    session_id: str,
    payload: AudioDegradationReportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Report network degradation and adapt audio bitrate/quality level."""
    participant = await VoiceService.report_degradation(
        session_id=session_id,
        user_id=current_user.id,
        quality_level=payload.quality_level,
        packet_loss=payload.packet_loss,
        db=db,
    )
    return {
        "is_in_audio_call": participant.is_in_audio_call,
        "is_audio_muted": participant.is_audio_muted,
        "audio_route": participant.audio_route,
        "audio_quality": participant.audio_quality,
        "participant_user_id": participant.user_id,
    }


@router.get("/{session_id}/audio/status", response_model=AudioStatusResponse)
async def get_audio_status(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get active audio call status for current user in session."""
    return await VoiceService.get_audio_status(
        session_id=session_id,
        user_id=current_user.id,
        db=db,
    )


# ---------------------------------------------------------------------------
# Remote Control Protocol Routes (Phase 6)
# ---------------------------------------------------------------------------


@router.post("/{session_id}/remote-control/grant", response_model=RemoteControlStatusResponse)
async def grant_remote_control(
    session_id: str,
    payload: RemoteControlGrantRequest = RemoteControlGrantRequest(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Grant remote control permission to session helper."""
    session = await RemoteControlService.grant_remote_control(
        session_id=session_id,
        user_id=current_user.id,
        platform=payload.platform,
        db=db,
    )
    return {
        "session_id": session.id,
        "remote_control_granted": session.remote_control_granted,
        "remote_control_granted_at": session.remote_control_granted_at,
        "remote_control_platform": session.remote_control_platform,
    }


@router.post("/{session_id}/remote-control/revoke", response_model=RemoteControlStatusResponse)
async def revoke_remote_control(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Instantly revoke remote control permission."""
    session = await RemoteControlService.revoke_remote_control(
        session_id=session_id,
        user_id=current_user.id,
        db=db,
    )
    return {
        "session_id": session.id,
        "remote_control_granted": session.remote_control_granted,
        "remote_control_granted_at": session.remote_control_granted_at,
        "remote_control_platform": session.remote_control_platform,
    }


@router.post("/{session_id}/remote-control/input")
async def dispatch_remote_control_input(
    session_id: str,
    payload: RemoteControlInputEvent,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dispatch remote gesture/key input event (Tap, Drag, Long Press, Gestures, Key Events)."""
    return await RemoteControlService.dispatch_input_event(
        session_id=session_id,
        user_id=current_user.id,
        input_event=payload,
        db=db,
    )


@router.get("/{session_id}/remote-control/status", response_model=RemoteControlStatusResponse)
async def get_remote_control_status(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get remote control permission status."""
    return await RemoteControlService.get_status(
        session_id=session_id,
        user_id=current_user.id,
        db=db,
    )
