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
from core.rate_limiter import limit_help_call_attempts
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
    helper_name: str


class HelpCallStatusResponse(BaseModel):
    request_id: str
    session_id: str
    status: str
    helper_name: str


@router.post(
    "/call",
    response_model=HelpCallResponse,
    dependencies=[Depends(limit_help_call_attempts)],
)
async def place_help_call(
    payload: HelpCallRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Helpee taps a trusted person: form session + ring the helper.

    Idempotent while ringing: if a request for this pair is already pending,
    we return it instead of erroring — tapping again just keeps calling.
    """
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

    await SessionService.ensure_helper_available(
        helpee_id=current_user.id,
        helper_id=helper_user_id,
        db=db,
    )

    # 2. Find-or-create the pair session (no codes involved).
    session = await SessionService.get_or_create_pair_session(
        helpee_id=current_user.id,
        helper_id=helper_user_id,
        db=db,
    )

    # 3. Reuse an already-pending request for this session if one exists.
    from models.assistance_request import AssistanceRequest

    result = await db.execute(
        select(AssistanceRequest).where(
            AssistanceRequest.session_id == session.id,
            AssistanceRequest.status == "pending",
        )
    )
    request = result.scalar_one_or_none()

    if request is None:
        # 3b. Create the assistance request (reuses all security checks).
        request = await AssistanceRequestService.request_help(
            session_id=session.id,
            helpee_user_id=current_user.id,
            helper_user_id=helper_user_id,
            helper_device_fingerprint=payload.helper_device_fingerprint,
            message=payload.message,
            db=db,
        )

    # 4. Ring every live device of the helper (also covers re-rings).
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

    # 5. Send FCM as well as the live channel. Android does not show a
    # notification automatically when the app is foregrounded, so the app
    # also turns this payload into a local heads-up notification.
    await _send_fcm_ring(
        helper_user_id,
        from_name=current_user.display_name or "Someone you help",
        message=payload.message,
        request_id=request.id,
        session_id=session.id,
        db=db,
    )

    helper = await db.get(User, helper_user_id)
    helper_name = (helper.display_name if helper else None) or trust.friendly_name or "your helper"

    return {
        "request_id": request.id,
        "session_id": session.id,
        "status": "ringing",
        "helper_online": helper_online,
        "helper_name": helper_name,
    }


@router.get("/call/{request_id}", response_model=HelpCallStatusResponse)
async def get_help_call_status(
    request_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the durable state of a help call.

    The device WebSocket is an optimization for instant updates, not the
    source of truth. Mobile clients poll this endpoint while ringing so a
    dropped socket cannot leave a caller stuck indefinitely.
    """
    from models.assistance_request import AssistanceRequest

    result = await db.execute(
        select(AssistanceRequest).where(AssistanceRequest.id == request_id)
    )
    request = result.scalar_one_or_none()
    if request is None:
        raise HTTPException(status_code=404, detail="Help request not found")
    if current_user.id not in (request.helpee_user_id, request.helper_user_id):
        raise HTTPException(status_code=403, detail="Not a participant in this help request")

    helper = await db.get(User, request.helper_user_id) if request.helper_user_id else None
    return {
        "request_id": request.id,
        "session_id": request.session_id,
        "status": request.status,
        "helper_name": (helper.display_name if helper else None) or "your helper",
    }


@router.post("/call/{request_id}/cancel", response_model=HelpCallStatusResponse)
async def cancel_help_call(
    request_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Stop an outgoing ring and notify the helper's live device channel."""
    request = await AssistanceRequestService.cancel_request(
        request_id=request_id,
        helpee_user_id=current_user.id,
        db=db,
    )
    await push_to_user(
        request.helper_user_id or "",
        {
            "type": "call_cancelled",
            "request_id": request.id,
            "session_id": request.session_id,
        },
    )
    return {
        "request_id": request.id,
        "session_id": request.session_id,
        "status": request.status,
        "helper_name": "your helper",
    }


@router.post("/push-token")
async def register_push_token(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Store this device's FCM token for closed-app ring notifications."""
    from models.device_account import DeviceAccount

    token = (payload or {}).get("token")
    if not token:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Missing push token")
    result = await db.execute(
        select(DeviceAccount).where(DeviceAccount.user_id == current_user.id)
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No device account for user")
    account.fcm_token = token
    await db.commit()
    return {"status": "registered"}


@router.get("/pending")
async def list_pending_calls(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Missed rings: pending requests addressed to ME (the helper).

    Shown as soon as the app opens — a closed app never loses a request.
    """
    from models.assistance_request import AssistanceRequest

    result = await db.execute(
        select(AssistanceRequest).where(
            AssistanceRequest.helper_user_id == current_user.id,
            AssistanceRequest.status == "pending",
        )
    )
    requests = result.scalars().all()

    items = []
    for req in requests:
        res = await db.execute(select(User).where(User.id == req.helpee_user_id))
        helpee = res.scalar_one_or_none()
        items.append(
            {
                "request_id": req.id,
                "session_id": req.session_id,
                "from_name": (helpee.display_name if helpee else None) or "Someone",
                "message": req.message,
                "created_at": req.created_at.isoformat(),
            }
        )
    return {"total": len(items), "items": items}


# Re-exported so the respond route can notify the helpee without circulars.
__all__ = ["router", "place_help_call", "is_user_online"]


async def _send_fcm_ring(
    helper_user_id: str,
    from_name: str,
    message: str | None,
    request_id: str,
    session_id: str,
    db: AsyncSession,
) -> None:
    """Best-effort FCM wake-up. Silently skips if credentials are absent."""
    import logging
    import os

    from models.device_account import DeviceAccount

    logger = logging.getLogger("uvicorn.error")

    creds_path = os.getenv(
        "FIREBASE_SERVICE_ACCOUNT",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                     "firebase-service-account.json"),
    )
    if not os.path.exists(creds_path):
        logger.warning("FCM skipped: %s not found (helper offline, push unavailable)",
                       creds_path)
        return

    result = await db.execute(
        select(DeviceAccount).where(DeviceAccount.user_id == helper_user_id)
    )
    account = result.scalar_one_or_none()
    if account is None or not account.fcm_token:
        return

    try:
        import firebase_admin
        from firebase_admin import credentials, messaging

        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(creds_path))

        title = f"{from_name} needs your help"
        body = (message or "Tap to respond")[:180]
        messaging.send(messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            token=account.fcm_token,
            data={
                "type": "incoming_call",
                "request_id": request_id,
                "session_id": session_id,
            },
            android=messaging.AndroidConfig(priority="high"),
        ))
    except Exception as exc:
        logger.warning("FCM send failed: %s", exc)
