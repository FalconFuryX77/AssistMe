"""Authentication business logic."""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from core.config import settings
from models.refresh_token import RefreshToken
from models.user import User


class AuthService:
    """Handles registration, login, token refresh, and logout."""

    @staticmethod
    async def register(
        email: str,
        password: str,
        display_name: str | None,
        db: AsyncSession,
    ) -> dict[str, str]:
        """Register a new user and return access + refresh tokens.

        Raises 400 if the email is already taken.
        """
        # Check for duplicate email
        result = await db.execute(select(User).where(User.email == email))
        if result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

        # Create user
        user = User(
            email=email,
            hashed_password=hash_password(password),
            display_name=display_name,
        )
        db.add(user)
        await db.flush()  # get user.id without committing

        # Generate tokens
        access_token = create_access_token(user.id)
        raw_refresh = create_refresh_token()

        refresh_record = RefreshToken(
            token=raw_refresh,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
        db.add(refresh_record)
        await db.commit()

        return {
            "access_token": access_token,
            "refresh_token": raw_refresh,
            "token_type": "bearer",
        }

    @staticmethod
    async def login(
        email: str,
        password: str,
        db: AsyncSession,
    ) -> dict[str, str]:
        """Authenticate a user and return tokens.

        Raises 401 on invalid credentials.
        """
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user is None or not verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        access_token = create_access_token(user.id)
        raw_refresh = create_refresh_token()

        refresh_record = RefreshToken(
            token=raw_refresh,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
        db.add(refresh_record)
        await db.commit()

        return {
            "access_token": access_token,
            "refresh_token": raw_refresh,
            "token_type": "bearer",
        }

    @staticmethod
    async def refresh(refresh_token: str, db: AsyncSession) -> dict[str, str]:
        """Issue a new access token using a valid refresh token.

        Raises 401 if the refresh token is invalid, expired, or revoked.
        """
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token == refresh_token)
        )
        record = result.scalar_one_or_none()

        if record is None or record.revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )

        if record.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )

        access_token = create_access_token(record.user_id)
        return {"access_token": access_token, "token_type": "bearer"}

    @staticmethod
    async def logout(refresh_token: str, db: AsyncSession) -> dict[str, str]:
        """Revoke a refresh token (logout).

        Raises 401 if the token is not found.
        """
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token == refresh_token)
        )
        record = result.scalar_one_or_none()

        if record is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )

        record.revoked = True
        await db.commit()

        return {"detail": "Successfully logged out"}
