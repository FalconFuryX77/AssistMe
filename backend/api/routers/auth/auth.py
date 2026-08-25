"""Authentication API routes."""

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.auth import AccessTokenResponse, DeviceBootstrapRequest, DeviceBootstrapResponse, RefreshTokenRequest
from api.services.auth_service import AuthService
from core.database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/device",
    response_model=DeviceBootstrapResponse,
    status_code=status.HTTP_201_CREATED,
)
async def device_bootstrap(
    payload: DeviceBootstrapRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Device-first identity: no email/password. First call creates the
    invisible account + one-time recovery code; later calls log back in."""
    return await AuthService.device_bootstrap(
        device_fingerprint=payload.device_fingerprint,
        display_name=payload.display_name,
        db=db,
    )


class ReclaimRequest(BaseModel):
    """Reclaim an identity after reinstall/phone loss using the recovery code."""

    device_fingerprint: str
    recovery_code: str

    @field_validator("recovery_code")
    @classmethod
    def code_shape(cls, v: str) -> str:
        v = v.strip().replace("-", "").replace(" ", "").lower()
        if len(v) < 8:
            raise ValueError("Recovery code looks too short")
        return v


@router.post("/device/reclaim", response_model=DeviceBootstrapResponse)
async def device_reclaim(
    payload: ReclaimRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Bind this install to the account matching the recovery code.

    This is the reinstall path: new fingerprint + old recovery code = same
    identity, same trusted people.
    """
    return await AuthService.device_reclaim(
        device_fingerprint=payload.device_fingerprint,
        recovery_code=payload.recovery_code,
        db=db,
    )


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh_token(
    payload: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Get a new access token using a refresh token."""
    return await AuthService.refresh(
        refresh_token=payload.refresh_token,
        db=db,
    )
