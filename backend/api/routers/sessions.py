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
from api.schemas.webrtc import ICEServersResponse
from api.services.screen_share_service import ScreenShareService
from api.services.session_service import SessionService
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
