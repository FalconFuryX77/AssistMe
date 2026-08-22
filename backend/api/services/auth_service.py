"""Authentication business logic."""

import secrets
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
from models.device_account import DeviceAccount
from models.refresh_token import RefreshToken
from models.user import User


class AuthService:
    """Handles registration, login, token refresh, logout, device bootstrap."""

    @staticmethod
    async def device_bootstrap(
        device_fingerprint: str,
        display_name: str | None,
        db: AsyncSession,
    ) -> dict:
        """Device-first identity: find-or-create the account for this install.

        First call creates an invisible user (no email/password known to the
        human) plus a hashed one-time recovery code. Later calls simply log
        the same identity back in and refresh tokens.
        """
        result = await db.execute(
            select(DeviceAccount).where(
                DeviceAccount.fingerprint == device_fingerprint
            )
        )
        account = result.scalar_one_or_none()

        recovery_code: str | None = None

        if account is None:
            # --- first launch: create invisible identity ---
            suffix = secrets.token_hex(8)
            random_password = secrets.token_urlsafe(24)
            user = User(
                email=f"device-{suffix}@assistme.internal",
                hashed_password=hash_password(random_password),
                display_name=display_name,
            )
            db.add(user)
            await db.flush()

            recovery_code = secrets.token_hex(6)  # 12 chars, shown once
            account = DeviceAccount(
                user_id=user.id,
                fingerprint=device_fingerprint,
                recovery_code_hash=AuthService._hash_recovery(recovery_code),
            )
            db.add(account)
            created = True
            resolved_name = display_name
        else:
            result = await db.execute(select(User).where(User.id == account.user_id))
            user = result.scalar_one_or_none()
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Device account is corrupted",
                )
            created = False
            if display_name and display_name != user.display_name:
                user.display_name = display_name
            resolved_name = user.display_name

        await db.flush()

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
            "user_id": user.id,
            "display_name": resolved_name,
            "created": created,
            "recovery_code": recovery_code,
        }

    @staticmethod
    async def device_reclaim(
        device_fingerprint: str,
        recovery_code: str,
        db: AsyncSession,
    ) -> dict:
        """Reclaim an identity with a recovery code (reinstall/phone loss).

        Verifies the code against the stored hash and rebinds THIS install's
        fingerprint to that account — trusted people come back with it.
        """
        code_hash = AuthService._hash_recovery(recovery_code)
        result = await db.execute(
            select(DeviceAccount).where(
                DeviceAccount.recovery_code_hash == code_hash
            )
        )
        account = result.scalar_one_or_none()
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No account matches that recovery code",
            )

        # Guard: another live install already holds this fingerprint.
        result = await db.execute(
            select(DeviceAccount).where(
                DeviceAccount.fingerprint == device_fingerprint
            )
        )
        clash = result.scalar_one_or_none()
        if clash is not None and clash.id != account.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This install already belongs to a different identity",
            )

        # Rebind: this physical install now IS that account.
        account.fingerprint = device_fingerprint
        await db.flush()

        result = await db.execute(select(User).where(User.id == account.user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Reclaimed account is corrupted",
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
            "user_id": user.id,
            "display_name": user.display_name,
            "created": False,
            "recovery_code": None,
        }

    @staticmethod
    def _hash_recovery(code: str) -> str:
        import hashlib

        return hashlib.sha256(code.strip().lower().encode("utf-8")).hexdigest()

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
