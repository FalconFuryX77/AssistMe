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
from api.schemas.adaptive_streaming import (
    NetworkMetricsReportRequest,
    StreamAdaptRequest,
    StreamConfigResponse,
)
from api.schemas.audit_recording import (
    AuditTrailResponse,
    RecordingConsentRequest,
    RecordingStartRequest,
    RecordingStatusResponse,
    RecordingStopRequest,
)
from api.schemas.e2ee import (
    E2EEKeyExchangeRequest,
    E2EEKeyRotationRequest,
    E2EESecurityStatusResponse,
    E2EEVerificationRequest,
)
from api.schemas.multiparty import (
    ActiveSpeakerSignalRequest,
    ActiveSpeakerStatusResponse,
    MultiPartyParticipantListResponse,
    ParticipantInviteRequest,
    ParticipantRoleUpdateRequest,
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
from api.services.adaptive_streaming_service import AdaptiveStreamingService
from api.services.audit_recording_service import AuditRecordingService
from api.services.e2ee_service import E2EEService
from api.services.multiparty_service import MultiPartyService
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
        "e2ee_enabled": session.e2ee_enabled,
        "e2ee_key_exchange_complete": session.e2ee_key_exchange_complete,
        "e2ee_fingerprint": session.e2ee_fingerprint,
        "e2ee_mitm_verified": session.e2ee_mitm_verified,
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
                "video_resolution": p.video_resolution,
                "video_bitrate_kbps": p.video_bitrate_kbps,
                "video_fps": p.video_fps,
                "rtt_ms": p.rtt_ms,
                "packet_loss_percent": p.packet_loss_percent,
                "is_active_speaker": p.is_active_speaker,
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


# ---------------------------------------------------------------------------
# Adaptive Streaming & Optimization Routes (Phase 7)
# ---------------------------------------------------------------------------


@router.post("/{session_id}/streaming/adapt", response_model=StreamConfigResponse)
async def adapt_stream(
    session_id: str,
    payload: StreamAdaptRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually adjust video stream resolution, bitrate, or frame rate."""
    participant = await AdaptiveStreamingService.adapt_stream(
        session_id=session_id,
        user_id=current_user.id,
        video_resolution=payload.video_resolution,
        video_bitrate_kbps=payload.video_bitrate_kbps,
        video_fps=payload.video_fps,
        db=db,
    )
    return {
        "video_resolution": participant.video_resolution,
        "video_bitrate_kbps": participant.video_bitrate_kbps,
        "video_fps": participant.video_fps,
        "rtt_ms": participant.rtt_ms,
        "packet_loss_percent": participant.packet_loss_percent,
        "auto_adapted": False,
        "participant_user_id": participant.user_id,
    }


@router.post("/{session_id}/streaming/metrics", response_model=StreamConfigResponse)
async def report_network_metrics(
    session_id: str,
    payload: NetworkMetricsReportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Report real-time client network metrics (RTT, jitter, packet loss) and auto-adapt video stream."""
    participant, auto_adapted = await AdaptiveStreamingService.process_network_metrics(
        session_id=session_id,
        user_id=current_user.id,
        rtt_ms=payload.rtt_ms,
        jitter_ms=payload.jitter_ms,
        packet_loss_percent=payload.packet_loss_percent,
        available_bandwidth_kbps=payload.available_bandwidth_kbps,
        db=db,
    )
    return {
        "video_resolution": participant.video_resolution,
        "video_bitrate_kbps": participant.video_bitrate_kbps,
        "video_fps": participant.video_fps,
        "rtt_ms": participant.rtt_ms,
        "packet_loss_percent": participant.packet_loss_percent,
        "auto_adapted": auto_adapted,
        "participant_user_id": participant.user_id,
    }


@router.get("/{session_id}/streaming/config", response_model=StreamConfigResponse)
async def get_stream_config(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get active video streaming configuration for user."""
    participant = await AdaptiveStreamingService.get_stream_config(
        session_id=session_id,
        user_id=current_user.id,
        db=db,
    )
    return {
        "video_resolution": participant.video_resolution,
        "video_bitrate_kbps": participant.video_bitrate_kbps,
        "video_fps": participant.video_fps,
        "rtt_ms": participant.rtt_ms,
        "packet_loss_percent": participant.packet_loss_percent,
        "auto_adapted": False,
        "participant_user_id": participant.user_id,
    }


# ---------------------------------------------------------------------------
# End-to-End Encryption (E2EE) Routes (Phase 8)
# ---------------------------------------------------------------------------


@router.post("/{session_id}/e2ee/keys/exchange", response_model=E2EESecurityStatusResponse)
async def exchange_e2ee_keys(
    session_id: str,
    payload: E2EEKeyExchangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Exchange E2EE identity keys and prekeys for WebRTC Insertable Streams."""
    session = await E2EEService.exchange_keys(
        session_id=session_id,
        user_id=current_user.id,
        identity_key=payload.identity_key,
        signed_prekey=payload.signed_prekey,
        ephemeral_key=payload.ephemeral_key,
        algorithm=payload.algorithm,
        db=db,
    )
    return {
        "session_id": session.id,
        "e2ee_enabled": session.e2ee_enabled,
        "key_exchange_complete": session.e2ee_key_exchange_complete,
        "fingerprint": session.e2ee_fingerprint,
        "is_mitm_verified": session.e2ee_mitm_verified,
    }


@router.post("/{session_id}/e2ee/keys/rotate", response_model=E2EESecurityStatusResponse)
async def rotate_e2ee_keys(
    session_id: str,
    payload: E2EEKeyRotationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Rotate Double Ratchet ephemeral keys for forward secrecy."""
    session = await E2EEService.rotate_keys(
        session_id=session_id,
        user_id=current_user.id,
        new_ephemeral_key=payload.new_ephemeral_key,
        ratchet_counter=payload.ratchet_counter,
        db=db,
    )
    return {
        "session_id": session.id,
        "e2ee_enabled": session.e2ee_enabled,
        "key_exchange_complete": session.e2ee_key_exchange_complete,
        "fingerprint": session.e2ee_fingerprint,
        "is_mitm_verified": session.e2ee_mitm_verified,
    }


@router.post("/{session_id}/e2ee/verify", response_model=E2EESecurityStatusResponse)
async def verify_e2ee_fingerprint(
    session_id: str,
    payload: E2EEVerificationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Verify SAS safety number fingerprint to prevent Man-In-The-Middle (MITM) attacks."""
    session = await E2EEService.verify_fingerprint(
        session_id=session_id,
        user_id=current_user.id,
        safety_number_fingerprint=payload.safety_number_fingerprint,
        is_verified_by_user=payload.is_verified_by_user,
        db=db,
    )
    return {
        "session_id": session.id,
        "e2ee_enabled": session.e2ee_enabled,
        "key_exchange_complete": session.e2ee_key_exchange_complete,
        "fingerprint": session.e2ee_fingerprint,
        "is_mitm_verified": session.e2ee_mitm_verified,
    }


@router.get("/{session_id}/e2ee/status", response_model=E2EESecurityStatusResponse)
async def get_e2ee_status(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get active E2EE status and security fingerprint for session."""
    return await E2EEService.get_status(
        session_id=session_id,
        user_id=current_user.id,
        db=db,
    )


# ---------------------------------------------------------------------------
# Session Recording & Audit Trails Routes (Phase 9)
# ---------------------------------------------------------------------------


@router.post("/{session_id}/recording/consent", response_model=RecordingStatusResponse)
async def update_recording_consent(
    session_id: str,
    payload: RecordingConsentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update session recording consent state."""
    session = await AuditRecordingService.update_consent(
        session_id=session_id,
        user_id=current_user.id,
        consent_granted=payload.consent_granted,
        recording_scope=payload.recording_scope,
        db=db,
    )
    return {
        "session_id": session.id,
        "is_recording": session.is_recording,
        "consent_granted": session.recording_consent_granted,
        "recording_scope": session.recording_scope,
        "recording_url": session.recording_url,
        "file_size_bytes": session.recording_file_size_bytes,
        "duration_seconds": session.recording_duration_seconds,
    }


@router.post("/{session_id}/recording/start", response_model=RecordingStatusResponse)
async def start_recording(
    session_id: str,
    payload: RecordingStartRequest = RecordingStartRequest(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Start session recording (requires recording_consent_granted == True)."""
    session = await AuditRecordingService.start_recording(
        session_id=session_id,
        user_id=current_user.id,
        storage_provider=payload.storage_provider,
        db=db,
    )
    return {
        "session_id": session.id,
        "is_recording": session.is_recording,
        "consent_granted": session.recording_consent_granted,
        "recording_scope": session.recording_scope,
        "recording_url": session.recording_url,
        "file_size_bytes": session.recording_file_size_bytes,
        "duration_seconds": session.recording_duration_seconds,
    }


@router.post("/{session_id}/recording/stop", response_model=RecordingStatusResponse)
async def stop_recording(
    session_id: str,
    payload: RecordingStopRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Stop active session recording and save file metadata."""
    session = await AuditRecordingService.stop_recording(
        session_id=session_id,
        user_id=current_user.id,
        file_url=payload.file_url,
        file_size_bytes=payload.file_size_bytes,
        duration_seconds=payload.duration_seconds,
        db=db,
    )
    return {
        "session_id": session.id,
        "is_recording": session.is_recording,
        "consent_granted": session.recording_consent_granted,
        "recording_scope": session.recording_scope,
        "recording_url": session.recording_url,
        "file_size_bytes": session.recording_file_size_bytes,
        "duration_seconds": session.recording_duration_seconds,
    }


@router.get("/{session_id}/recording/status", response_model=RecordingStatusResponse)
async def get_recording_status(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get recording status and metadata for session."""
    return await AuditRecordingService.get_recording_status(
        session_id=session_id,
        user_id=current_user.id,
        db=db,
    )


@router.get("/{session_id}/audit-trail", response_model=AuditTrailResponse)
async def get_session_audit_trail(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Retrieve privacy compliance audit logs for session."""
    return await AuditRecordingService.get_audit_trail(
        session_id=session_id,
        user_id=current_user.id,
        db=db,
    )


# ---------------------------------------------------------------------------
# Multi-party Assistance Sessions Routes (Phase 10)
# ---------------------------------------------------------------------------


@router.post("/{session_id}/participants/invite", response_model=ParticipantResponse)
async def invite_participant(
    session_id: str,
    payload: ParticipantInviteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Invite secondary helper or observer to session."""
    participant = await MultiPartyService.invite_participant(
        session_id=session_id,
        current_user_id=current_user.id,
        email_or_user_id=payload.email_or_user_id,
        role=payload.role,
        db=db,
    )
    return {
        "id": participant.id,
        "user_id": participant.user_id,
        "role": participant.role,
        "status": participant.status,
        "joined_at": participant.joined_at,
        "last_seen_at": participant.last_seen_at,
        "is_screen_sharing": participant.is_screen_sharing,
        "screen_share_platform": participant.screen_share_platform,
        "is_flag_secure_active": participant.is_flag_secure_active,
        "screen_orientation": participant.screen_orientation,
        "is_in_audio_call": participant.is_in_audio_call,
        "is_audio_muted": participant.is_audio_muted,
        "audio_route": participant.audio_route,
        "audio_quality": participant.audio_quality,
        "video_resolution": participant.video_resolution,
        "video_bitrate_kbps": participant.video_bitrate_kbps,
        "video_fps": participant.video_fps,
        "rtt_ms": participant.rtt_ms,
        "packet_loss_percent": participant.packet_loss_percent,
        "is_active_speaker": participant.is_active_speaker,
    }


@router.patch("/{session_id}/participants/{participant_id}/role", response_model=ParticipantResponse)
async def update_participant_role(
    session_id: str,
    participant_id: str,
    payload: ParticipantRoleUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update participant role in multi-party session."""
    participant = await MultiPartyService.update_participant_role(
        session_id=session_id,
        current_user_id=current_user.id,
        target_participant_id=participant_id,
        new_role=payload.role,
        db=db,
    )
    return {
        "id": participant.id,
        "user_id": participant.user_id,
        "role": participant.role,
        "status": participant.status,
        "joined_at": participant.joined_at,
        "last_seen_at": participant.last_seen_at,
        "is_screen_sharing": participant.is_screen_sharing,
        "screen_share_platform": participant.screen_share_platform,
        "is_flag_secure_active": participant.is_flag_secure_active,
        "screen_orientation": participant.screen_orientation,
        "is_in_audio_call": participant.is_in_audio_call,
        "is_audio_muted": participant.is_audio_muted,
        "audio_route": participant.audio_route,
        "audio_quality": participant.audio_quality,
        "video_resolution": participant.video_resolution,
        "video_bitrate_kbps": participant.video_bitrate_kbps,
        "video_fps": participant.video_fps,
        "rtt_ms": participant.rtt_ms,
        "packet_loss_percent": participant.packet_loss_percent,
        "is_active_speaker": participant.is_active_speaker,
    }


@router.post("/{session_id}/active-speaker", response_model=ActiveSpeakerStatusResponse)
async def set_active_speaker(
    session_id: str,
    payload: ActiveSpeakerSignalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Signal active speaker for multi-stream video layout routing."""
    return await MultiPartyService.set_active_speaker(
        session_id=session_id,
        current_user_id=current_user.id,
        active_speaker_user_id=payload.active_speaker_user_id,
        audio_level_db=payload.audio_level_db,
        db=db,
    )


@router.get("/{session_id}/participants", response_model=MultiPartyParticipantListResponse)
async def list_session_participants(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get all participants in multi-party session."""
    return await MultiPartyService.get_participants(
        session_id=session_id,
        current_user_id=current_user.id,
        db=db,
    )
