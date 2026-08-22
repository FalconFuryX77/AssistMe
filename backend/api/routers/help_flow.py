"""One-tap help flow — tap a trusted person, their phone rings.

Replaces the session-code dance: the helpee taps a contact, the backend forms
(or reuses) the session silently and pushes `incoming_call` to the helper's
persistent device channel. Accept/deny are pushed back the same way.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.routers.device_ws import is_user_online, push_to_user
from api.services.assistance_request_service import AssistanceRequestService
from api.services.session_service import SessionService
from core.database import get_db
from models.trusted_device import TrustedDevice
from models.user import User

router = APIRouter(prefix="/help", tags=["help-flow"])


class HelpCallRequest(BaseModel):
    """Tap-to-ring payload. The fingerprint must already be trusted."""

    helper_device_fingerprint: str = Field(min_length=16, max_length=128)
    message: str | None = Field(default=None, max_length=500)


class HelpCallResponse(BaseModel):
    request_id: str
    session_id: str
    status: str
    helper_online: bool


@router.post("/call", response_model=HelpCallResponse)
async def place_help_call(
    payload: HelpCallRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Helpee taps a trusted person: form session + ring the helper."""
    # 1. Resolve the helper from MY trusted list (security gate).
    result = await db.execute(
        select(TrustedDevice).where(
            TrustedDevice.owner_user_id == current_user.id,
            TrustedDevice.device_fingerprint == payload.helper_device_fingerprint,
            TrustedDevice.status == "accepted",
        )
    )
    trust = result.scalar_one_or_none()
    if trust is None or not trust.helper_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="That device is not in your trusted list",
        )

    helper_user_id = trust.helper_user_id

    # 2. Find-or-create the pair session (no codes involved).
    session = await SessionService.get_or_create_pair_session(
        helpee_id=current_user.id,
        helper_id=helper_user_id,
        db=db,
    )

    # 3. Create the assistance request (reuses all existing security checks).
    request = await AssistanceRequestService.request_help(
        session_id=session.id,
        helpee_user_id=current_user.id,
        helper_user_id=helper_user_id,
        helper_device_fingerprint=payload.helper_device_fingerprint,
        db=db,
    )

    # 4. Ring every live device of the helper.
    helper_online = await push_to_user(
        helper_user_id,
        {
            "type": "incoming_call",
            "request_id": request.id,
            "session_id": session.id,
            "from_user_id": current_user.id,
            "from_name": current_user.display_name or "Someone you help",
            "message": payload.message,
        },
    )

    return {
        "request_id": request.id,
        "session_id": session.id,
        "status": "ringing",
        "helper_online": helper_online,
    }


# Re-exported so the respond route can notify the helpee without circulars.
__all__ = ["router", "place_help_call", "is_user_online"]
