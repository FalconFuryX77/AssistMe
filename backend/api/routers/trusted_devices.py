"""Trusted-person pairing and one-tap approval routes."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas.trusted_device import (
    DeviceApproveRequest,
    DeviceApproveResponse,
    DeviceAuthRequest,
    DeviceAuthResponse,
    DeviceClaimRequest,
    DeviceClaimResponse,
    DeviceSetupCodeRequest,
    DeviceSetupCodeResponse,
    PendingPairingResponse,
    PendingPairingsResponse,
    TrustedDeviceListResponse,
    TrustedDeviceResponse,
)
from api.services.trusted_device_service import TrustedDeviceService
from core.database import get_db
from models.user import User

router = APIRouter(prefix="/devices", tags=["trusted-devices"])


@router.post(
    "/pairing/setup-code",
    response_model=DeviceSetupCodeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_setup_code(
    payload: DeviceSetupCodeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Issue a setup code the owner reads aloud to their helper.

    The helper then claims it on their own device; the owner approves with
    one tap. No fingerprint/password needed on the owner's side.
    """
    pairing_id, code, expires_at = await TrustedDeviceService.generate_setup_code(
        owner_user_id=current_user.id,
        db=db,
    )
    return {
        "pairing_id": pairing_id,
        "setup_code": code,
        "expires_at": expires_at,
    }


@router.post(
    "/pairing/claim",
    response_model=DeviceClaimResponse,
)
async def claim_setup_code(
    payload: DeviceClaimRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Helper claims a pairing by entering the code read aloud to them."""
    pairing = await TrustedDeviceService.claim_setup_code(
        setup_code=payload.setup_code,
        device_fingerprint=payload.device_fingerprint,
        friendly_name=payload.friendly_name,
        device_platform=payload.device_platform,
        claimer_user_id=current_user.id,
        db=db,
    )
    return {
        "pairing_id": pairing.id,
        "status": pairing.status,
    }


@router.get("/pairing/pending", response_model=PendingPairingsResponse)
async def list_pending_pairings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return pairings awaiting the owner's one-tap approval."""
    pairings = await TrustedDeviceService.list_pending_pairings(
        owner_user_id=current_user.id,
        db=db,
    )
    return {
        "total": len(pairings),
        "pairings": [PendingPairingResponse.from_pairing(p) for p in pairings],
    }


@router.post(
    "/pairing/approve",
    response_model=DeviceApproveResponse,
)
async def approve_pairing(
    payload: DeviceApproveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Owner approves a claimed pairing with one tap (no password)."""
    device = await TrustedDeviceService.approve_pairing(
        owner_user_id=current_user.id,
        pairing_id=payload.pairing_id,
        db=db,
    )
    return {
        "device_id": device.id,
        "device_fingerprint": device.device_fingerprint,
        "friendly_name": device.friendly_name,
        "status": device.status,
    }


@router.get("/helping")
async def list_helping(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The helper's address book: people this user can help (mutual trust)."""
    entries = await TrustedDeviceService.list_helping(current_user.id, db)
    return {"total": len(entries), "entries": entries}


@router.get("/", response_model=TrustedDeviceListResponse)
async def list_devices(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List the current user's trusted devices."""
    devices = await TrustedDeviceService.list_devices(
        owner_user_id=current_user.id,
        db=db,
    )
    response_devices = []
    for device in devices:
        data = TrustedDeviceResponse.model_validate(device).model_dump()
        helper = (
            await db.get(User, device.helper_user_id)
            if device.helper_user_id
            else None
        )
        data["helper_display_name"] = helper.display_name if helper else None
        data["device_tag"] = device.id.replace("-", "")[:6].upper()
        response_devices.append(data)
    return {
        "total": len(devices),
        "devices": response_devices,
    }


@router.delete(
    "/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_device(
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke a trusted device (owner's one-tap consent, no password)."""
    await TrustedDeviceService.revoke_device(
        owner_user_id=current_user.id,
        device_id=device_id,
        db=db,
    )


@router.post("/identity", response_model=DeviceAuthResponse)
async def check_device_identity(
    payload: DeviceAuthRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Check whether the current user's device is trusted to assist them.

    Note: in this endpoint, `owner_user_id` is the current user and we verify
    against their own trusted list. The helper's identity check happens when a
    helper requests a session — see TrustedDeviceService.verify_device_identity.
    """
    return await TrustedDeviceService.verify_device_identity(
        owner_user_id=current_user.id,
        device_fingerprint=payload.device_fingerprint,
        db=db,
    )
