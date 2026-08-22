"""Assistance request & escalation API routes (one-click help flow)."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.routers.device_ws import push_to_user
from api.schemas.assistance_request import (
    AssistanceRequestCreate,
    AssistanceRequestRespond,
    AssistanceRequestResponse,
    EscalationCreate,
    EscalationRespond,
    EscalationResponse,
)
from api.services.assistance_request_service import AssistanceRequestService
from core.database import get_db
from models.user import User

router = APIRouter(prefix="/sessions/{session_id}/assistance", tags=["assistance"])


@router.post(
    "/request",
    response_model=AssistanceRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_help(
    session_id: str,
    payload: AssistanceRequestCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """A helpee requests help from a helper on their trusted device."""
    request = await AssistanceRequestService.request_help(
        session_id=session_id,
        helpee_user_id=current_user.id,
        helper_user_id=payload.helper_user_id,
        helper_device_fingerprint=payload.helper_device_fingerprint,
        db=db,
    )
    return _request_to_dict(request)


@router.post("/request/{request_id}/respond", response_model=AssistanceRequestResponse)
async def respond_to_request(
    session_id: str,
    request_id: str,
    payload: AssistanceRequestRespond,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The helper accepts or denies a pending assistance request."""
    request = await AssistanceRequestService.respond_to_request(
        request_id=request_id,
        helper_user_id=current_user.id,
        accept=payload.accept,
        helper_device_fingerprint=payload.helper_device_fingerprint,
        db=db,
    )

    # Ring the helpee's device channel with the outcome (works app-wide).
    await push_to_user(
        request.helpee_user_id,
        {
            "type": "call_accepted" if payload.accept else "call_denied",
            "request_id": request.id,
            "session_id": request.session_id,
            "helper_name": current_user.display_name or "Your helper",
        },
    )
    return _request_to_dict(request)


@router.post(
    "/escalation",
    response_model=EscalationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_escalation(
    session_id: str,
    payload: EscalationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """A helper requests more control (triggers a risk disclaimer for the helpee)."""
    escalation = await AssistanceRequestService.request_escalation(
        session_id=session_id,
        helper_user_id=current_user.id,
        target_capabilities=payload.target_capabilities,
        db=db,
    )
    return _escalation_to_dict(escalation)


@router.get("/escalation/{escalation_id}", response_model=EscalationResponse)
async def get_escalation(
    session_id: str,
    escalation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fetch an escalation (e.g. to display its disclaimer to the helpee)."""
    escalation = await AssistanceRequestService.get_escalation(escalation_id, db)
    return _escalation_to_dict(escalation)


@router.post(
    "/escalation/{escalation_id}/respond",
    response_model=EscalationResponse,
)
async def respond_to_escalation(
    session_id: str,
    escalation_id: str,
    payload: EscalationRespond,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The helpee responds to an escalation. Control granted only if risks accepted."""
    escalation = await AssistanceRequestService.respond_to_escalation(
        escalation_id=escalation_id,
        helpee_user_id=current_user.id,
        accept=payload.accept,
        accept_disclaimer=payload.accept_disclaimer,
        db=db,
    )
    return _escalation_to_dict(escalation)


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _request_to_dict(request) -> dict:
    import json

    caps = []
    if request.initial_capabilities:
        try:
            caps = json.loads(request.initial_capabilities)
        except (TypeError, ValueError):
            caps = []
    return {
        "id": request.id,
        "session_id": request.session_id,
        "helpee_user_id": request.helpee_user_id,
        "helper_user_id": request.helper_user_id,
        "helper_device_fingerprint": request.helper_device_fingerprint,
        "status": request.status,
        "initial_capabilities": caps,
        "responded_at": request.responded_at,
        "created_at": request.created_at,
    }


def _escalation_to_dict(escalation) -> dict:
    import json

    def _loads(value):
        if not value:
            return []
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return []

    return {
        "id": escalation.id,
        "session_id": escalation.session_id,
        "requested_by_user_id": escalation.requested_by_user_id,
        "target_capabilities": _loads(escalation.target_capabilities),
        "status": escalation.status,
        "disclaimer_text": escalation.disclaimer_text,
        "disclaimer_accepted": escalation.disclaimer_accepted,
        "granted_capabilities": _loads(escalation.granted_capabilities),
        "responded_at": escalation.responded_at,
        "created_at": escalation.created_at,
    }
