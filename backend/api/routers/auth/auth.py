"""Authentication API routes."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas.auth import (
    AccessTokenResponse,
    AuthResponse,
    DeviceBootstrapRequest,
    DeviceBootstrapResponse,
    LoginRequest,
    MessageResponse,
    RefreshTokenRequest,
    RegisterRequest,
)
from api.services.auth_service import AuthService
from core.database import get_db
from models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Register a new user account."""
    return await AuthService.register(
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
        db=db,
    )


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


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Authenticate with email and password."""
    return await AuthService.login(
        email=payload.email,
        password=payload.password,
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


@router.post("/logout", response_model=MessageResponse)
async def logout(
    payload: RefreshTokenRequest,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Revoke the refresh token (log out)."""
    return await AuthService.logout(
        refresh_token=payload.refresh_token,
        db=db,
    )
