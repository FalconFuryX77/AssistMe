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
from api.schemas.webrtc import ICEServersResponse
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
