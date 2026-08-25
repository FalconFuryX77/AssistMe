"""The small REST surface needed by a two-person live help session."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas.remote_control import RemoteControlInputEvent
from api.schemas.sessions import SessionCreateRequest, SessionJoinRequest, SessionListItem, SessionRecoverRequest, SessionResponse
from api.schemas.voice import AudioMuteToggleRequest, AudioStatusResponse
from api.schemas.webrtc import ICEServersResponse
from api.services.remote_control_service import RemoteControlService
from api.services.session_service import SessionService
from api.services.voice_service import VoiceService
from api.services.webrtc_service import WebRTCService
from core.database import get_db
from models.session import Session
from models.user import User

router = APIRouter(prefix="/sessions", tags=["live-help"])


def _enrich_session(session: Session) -> dict:
    return {
        "id": session.id, "creator_id": session.creator_id, "status": session.status,
        "title": session.title, "session_code": session.session_code,
        "timeout_minutes": session.timeout_minutes,
        "remote_control_granted": session.remote_control_granted,
        "remote_control_granted_at": session.remote_control_granted_at,
        "remote_control_platform": session.remote_control_platform,
        "e2ee_enabled": session.e2ee_enabled, "created_at": session.created_at,
        "updated_at": session.updated_at, "ended_at": session.ended_at,
        "participants": [
            {
                "id": p.id, "user_id": p.user_id, "role": p.role, "status": p.status,
                "joined_at": p.joined_at, "last_seen_at": p.last_seen_at,
            }
            for p in session.participants
        ],
    }


@router.post("/", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(payload: SessionCreateRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return _enrich_session(await SessionService.create_session(creator_id=current_user.id, title=payload.title, timeout_minutes=payload.timeout_minutes, db=db))


@router.post("/join", response_model=SessionResponse)
async def join_session(payload: SessionJoinRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return _enrich_session(await SessionService.join_session(session_code=payload.session_code, user_id=current_user.id, db=db))


@router.get("/", response_model=list[SessionListItem])
async def list_sessions(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[dict]:
    return await SessionService.list_sessions(user_id=current_user.id, status_filter=None, db=db)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return _enrich_session(await SessionService.get_session(session_id=session_id, user_id=current_user.id, db=db))


@router.get("/{session_id}/ice-servers", response_model=ICEServersResponse, response_model_exclude_none=True)
async def get_ice_servers(session_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> ICEServersResponse:
    await SessionService.get_session(session_id=session_id, user_id=current_user.id, db=db)
    return WebRTCService.get_ice_servers()


@router.post("/{session_id}/leave", response_model=SessionResponse)
async def leave_session(session_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return _enrich_session(await SessionService.leave_session(session_id=session_id, user_id=current_user.id, db=db))


@router.post("/{session_id}/end", response_model=SessionResponse)
async def end_session(session_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return _enrich_session(await SessionService.end_session(session_id=session_id, user_id=current_user.id, db=db))


@router.post("/recover", response_model=SessionResponse)
async def recover_session(payload: SessionRecoverRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return _enrich_session(await SessionService.recover_session(session_id=payload.session_id, user_id=current_user.id, db=db))


@router.post("/{session_id}/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
async def heartbeat(session_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> None:
    await SessionService.heartbeat(session_id=session_id, user_id=current_user.id, db=db)


@router.post("/{session_id}/audio/mute", response_model=AudioStatusResponse)
async def toggle_audio_mute(session_id: str, payload: AudioMuteToggleRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    participant = await VoiceService.toggle_mute(session_id=session_id, user_id=current_user.id, is_muted=payload.is_muted, db=db)
    return {"is_in_audio_call": participant.is_in_audio_call, "is_audio_muted": participant.is_audio_muted, "audio_route": participant.audio_route, "audio_quality": participant.audio_quality, "participant_user_id": participant.user_id}


@router.post("/{session_id}/remote-control/input")
async def dispatch_remote_control_input(session_id: str, payload: RemoteControlInputEvent, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    return await RemoteControlService.dispatch_input_event(session_id=session_id, user_id=current_user.id, input_event=payload, db=db)
