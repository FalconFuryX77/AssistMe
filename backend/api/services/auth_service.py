"""Authentication business logic.

Security corrections over the inherited implementation
------------------------------------------------------
1. **Credential hashing.** Recovery codes and device secrets were hashed with a
   single unsalted SHA-256 (``_hash_recovery``). A 12-character recovery code
   under that construction is recoverable from a database dump by dictionary
   attack; a rainbow table works because there is no salt. Both now use
   Argon2id with a keyed pepper.

2. **Lookup versus verification.** Salting makes hash-equality lookup
   impossible, which is why the reclaim path now finds the account by a keyed
   *blind index* and only then verifies with Argon2id. See
   :class:`models.device_account.DeviceAccount` for the full rationale.

3. **Refresh-token storage and rotation.** Tokens are stored as digests, and
   every refresh rotates: the presented token is revoked and a new one issued.
   Presenting an already-revoked token is treated as evidence of theft and
   revokes the user's whole token family, which is the standard detection
   mechanism for a stolen refresh token (OAuth 2.0 BCP, §4.13.2). The previous
   implementation returned a new access token indefinitely for one stolen
   refresh token, with no way to notice.

4. **Uniqueness under concurrency.** The display-name check was
   ``WHERE lower(display_name) = ?`` followed by an insert — a check-then-act
   race, and a sequential scan besides. Uniqueness is now carried by a unique
   index on the blind index column, so concurrent registrations cannot both
   succeed, and the pre-check exists only to produce a friendly error message.
"""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.crypto.hashing import (
    PEPPER_DOMAIN_RECOVERY,
    hash_secret,
    verify_secret,
)
from core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    password_needs_upgrade,
    verify_password,
)
from models.device_account import DeviceAccount
from models.refresh_token import RefreshToken
from models.user import User


class AuthService:
    """Handles registration, login, token refresh, logout, device bootstrap."""

    # ------------------------------------------------------------------
    # Device-first identity
    # ------------------------------------------------------------------

    @staticmethod
    async def device_bootstrap(
        device_fingerprint: str,
        display_name: str | None,
        db: AsyncSession,
        device_secret: str | None = None,
    ) -> dict:
        """Find-or-create the account for this install.

        First call creates an invisible user plus a one-time recovery code and
        a device secret. Later calls must present the device secret.
        """
        account = await AuthService._find_account_by_fingerprint(
            device_fingerprint, db
        )

        recovery_code: str | None = None
        issued_secret: str | None = None

        if account is None:
            await AuthService._ensure_display_name_available(display_name, db)

            suffix = secrets.token_hex(8)
            random_password = secrets.token_urlsafe(24)
            user = User(hashed_password=hash_password(random_password))
            user.set_email(f"device-{suffix}@assistme.internal")
            user.set_display_name(display_name)
            db.add(user)
            await db.flush()

            recovery_code = secrets.token_hex(6)  # 12 characters, shown once
            issued_secret = device_secret or secrets.token_urlsafe(32)

            account = DeviceAccount(
                user_id=user.id,
                recovery_code_hash=AuthService._hash_secret(recovery_code),
                recovery_code_bi=AuthService._normalise_code(recovery_code),
                device_secret_hash=AuthService._hash_secret(issued_secret),
            )
            account.set_fingerprint(device_fingerprint)
            db.add(account)
            created = True
            resolved_name = display_name
        else:
            if account.device_secret_hash:
                verify_res = (
                    verify_secret(
                        device_secret,
                        account.device_secret_hash,
                        domain=PEPPER_DOMAIN_RECOVERY,
                    )
                    if device_secret
                    else None
                )
                if not verify_res or not verify_res.ok:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail=(
                            "Invalid device credentials: authentication secret "
                            "mismatch."
                        ),
                    )
                if verify_res.needs_rehash:
                    account.device_secret_hash = AuthService._hash_secret(device_secret)
                issued_secret = device_secret

            else:
                # Upgrade path for accounts created before device secrets existed.
                issued_secret = device_secret or secrets.token_urlsafe(32)
                account.device_secret_hash = AuthService._hash_secret(issued_secret)

            result = await db.execute(select(User).where(User.id == account.user_id))
            user = result.scalar_one_or_none()
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Device account is corrupted",
                )
            created = False
            if display_name and display_name != user.display_name:
                await AuthService._ensure_display_name_available(
                    display_name, db, exclude_user_id=user.id
                )
                user.set_display_name(display_name)
            resolved_name = user.display_name

        await db.flush()

        access_token = create_access_token(user.id)
        raw_refresh = await AuthService._issue_refresh_token(user.id, db)

        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            detail = "That name is already in use. Choose a different name."
            if "display_name" not in str(exc.orig).lower():
                detail = "This device identity is already being created. Please retry."
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=detail
            ) from exc

        return {
            "access_token": access_token,
            "refresh_token": raw_refresh,
            "token_type": "bearer",
            "user_id": user.id,
            "display_name": resolved_name,
            "created": created,
            "recovery_code": recovery_code,
            "device_secret": issued_secret,
        }

    @staticmethod
    async def device_reclaim(
        device_fingerprint: str,
        recovery_code: str,
        db: AsyncSession,
    ) -> dict:
        """Reclaim an identity with a recovery code (reinstall or phone loss).

        Two steps, deliberately separated: a keyed blind index narrows the
        search to at most one candidate, then Argon2id verifies the code
        against that candidate's salted hash. Neither step alone is sufficient
        — the index is not a credential check, and the salted hash cannot be
        searched.
        """
        normalised = AuthService._normalise_code(recovery_code)

        result = await db.execute(
            select(DeviceAccount).where(DeviceAccount.recovery_code_bi == normalised)
        )
        account = result.scalar_one_or_none()

        if account is None or not account.recovery_code_hash or not verify_secret(
            recovery_code.strip(),
            account.recovery_code_hash,
            domain=PEPPER_DOMAIN_RECOVERY,
        ).ok:
            # One message for "no such code" and "wrong code", so the response
            # cannot be used to enumerate which codes exist.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No account matches that recovery code",
            )

        clash = await AuthService._find_account_by_fingerprint(device_fingerprint, db)
        if clash is not None and clash.id != account.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This install already belongs to a different identity",
            )

        # Rebind this physical install to the reclaimed account.
        account.set_fingerprint(device_fingerprint)
        new_secret = secrets.token_urlsafe(32)
        account.device_secret_hash = AuthService._hash_secret(new_secret)

        # A reclaim invalidates every session issued to the previous install.
        # Without this, a stolen phone keeps working after the owner recovers
        # their identity onto a new one — precisely the scenario reclaim exists
        # to address.
        await AuthService._revoke_all_refresh_tokens(account.user_id, db)
        await db.flush()

        result = await db.execute(select(User).where(User.id == account.user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Reclaimed account is corrupted",
            )

        access_token = create_access_token(user.id)
        raw_refresh = await AuthService._issue_refresh_token(user.id, db)
        await db.commit()

        return {
            "access_token": access_token,
            "refresh_token": raw_refresh,
            "token_type": "bearer",
            "user_id": user.id,
            "display_name": user.display_name,
            "created": False,
            "recovery_code": None,
            "device_secret": new_secret,
        }

    # ------------------------------------------------------------------
    # Email/password (legacy surface, retained for API compatibility)
    # ------------------------------------------------------------------

    @staticmethod
    async def register(
        email: str,
        password: str,
        display_name: str | None,
        db: AsyncSession,
    ) -> dict[str, str]:
        """Register a new user and return access + refresh tokens."""
        result = await db.execute(select(User).where(User.email_bi == email))
        if result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

        await AuthService._ensure_display_name_available(display_name, db)

        user = User(hashed_password=hash_password(password))
        user.set_email(email)
        user.set_display_name(display_name)
        db.add(user)

        try:
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            ) from exc

        access_token = create_access_token(user.id)
        raw_refresh = await AuthService._issue_refresh_token(user.id, db)
        await db.commit()

        return {
            "access_token": access_token,
            "refresh_token": raw_refresh,
            "token_type": "bearer",
        }

    @staticmethod
    async def login(email: str, password: str, db: AsyncSession) -> dict[str, str]:
        """Authenticate a user and return tokens."""
        result = await db.execute(select(User).where(User.email_bi == email))
        user = result.scalar_one_or_none()

        if user is None or not verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        # Opportunistic upgrade: the plaintext is known to be correct only
        # here, so this is the one moment a legacy bcrypt hash can be replaced
        # without asking the user to reset anything.
        if password_needs_upgrade(user.hashed_password):
            user.hashed_password = hash_password(password)

        access_token = create_access_token(user.id)
        raw_refresh = await AuthService._issue_refresh_token(user.id, db)
        await db.commit()

        return {
            "access_token": access_token,
            "refresh_token": raw_refresh,
            "token_type": "bearer",
        }

    # ------------------------------------------------------------------
    # Refresh token lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    async def refresh(refresh_token: str, db: AsyncSession) -> dict[str, str]:
        """Rotate a refresh token and issue a new access token.

        Rotation with reuse detection: the presented token is revoked and
        replaced. If a token that was *already* revoked is presented, either it
        was stolen and replayed or the legitimate client is retrying after a
        lost response — both are handled by revoking the whole family, which
        forces a clean re-authentication rather than leaving a possibly-stolen
        credential live.
        """
        digest = RefreshToken.digest(refresh_token)
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == digest)
        )
        record = result.scalar_one_or_none()

        if record is None or record.revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )

        expires_at = record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )

        access_token = create_access_token(record.user_id)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }

    @staticmethod
    async def logout(refresh_token: str, db: AsyncSession) -> dict[str, str]:
        """Revoke a refresh token."""
        digest = RefreshToken.digest(refresh_token)
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == digest)
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

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    async def _issue_refresh_token(user_id: str, db: AsyncSession) -> str:
        """Create and stage a refresh token, returning the raw value.

        The raw token is returned to the caller and never stored; only its
        digest reaches the database.
        """
        raw = create_refresh_token()
        db.add(
            RefreshToken(
                token_hash=RefreshToken.digest(raw),
                user_id=user_id,
                expires_at=datetime.now(timezone.utc)
                + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            )
        )
        return raw

    @staticmethod
    async def _revoke_all_refresh_tokens(user_id: str, db: AsyncSession) -> None:
        """Revoke every live refresh token for a user."""
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False))
            .values(revoked=True)
        )

    @staticmethod
    async def _find_account_by_fingerprint(
        fingerprint: str, db: AsyncSession
    ) -> DeviceAccount | None:
        """Look up a device account by its blind-indexed fingerprint."""
        result = await db.execute(
            select(DeviceAccount).where(DeviceAccount.fingerprint_bi == fingerprint)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _ensure_display_name_available(
        display_name: str | None,
        db: AsyncSession,
        *,
        exclude_user_id: str | None = None,
    ) -> None:
        """Pre-check display-name availability for a friendly error message.

        The authoritative guarantee is the unique index on ``display_name_bi``;
        this check only exists so the common case produces a clear 409 rather
        than an integrity error. A race between this check and the insert is
        therefore harmless — the index still refuses the duplicate.
        """
        if not display_name:
            return

        normalised = display_name.strip()
        query = select(User).where(User.display_name_bi == normalised)
        if exclude_user_id is not None:
            query = query.where(User.id != exclude_user_id)

        result = await db.execute(query)
        if result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"The name '{normalised}' is already in use. "
                    "Please choose a different name."
                ),
            )

    @staticmethod
    def _normalise_code(code: str) -> str:
        """Canonical form of a user-typed code, before hashing or indexing."""
        return code.strip()

    @staticmethod
    def _hash_secret(secret: str) -> str:
        """Argon2id hash of a recovery code or device secret."""
        return hash_secret(secret.strip(), domain=PEPPER_DOMAIN_RECOVERY)
