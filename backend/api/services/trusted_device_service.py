"""Trusted device business logic — pairing, password-gated management, identity."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import verify_password
from models.trusted_device import DevicePairing, TrustedDevice
from models.user import User

PAIRING_CODE_TTL_MINUTES = 15
PAIRING_CODE_LENGTH = 6


def _sha256(value: str) -> str:
    """Return a hex SHA-256 digest of the input."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_expired(expires_at: datetime) -> bool:
    """Compare database timestamps safely across PostgreSQL and SQLite.

    PostgreSQL preserves timezone-aware values while SQLite commonly returns
    naive values for the same SQLAlchemy column. Normalize both to UTC before
    comparing so pairing does not fail with a TypeError in production.
    """
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) > expires_at


class TrustedDeviceService:
    """Manages device pairing, trusted-list security, and device identity."""

    @staticmethod
    def _generate_pairing_code() -> str:
        """Generate a human-friendly 6-digit pairing code."""
        return "".join(str(secrets.randbelow(10)) for _ in range(PAIRING_CODE_LENGTH))

    # ------------------------------------------------------------------
    # Pairing
    # ------------------------------------------------------------------

    @staticmethod
    async def initiate_pairing(
        owner_user_id: str,
        device_fingerprint: str,
        friendly_name: str | None,
        device_platform: str | None,
        db: AsyncSession,
    ) -> tuple[str, str, datetime]:
        """Start pairing a new device. Returns (pairing_id, code, expires_at).

        If the device is already accepted for this owner, returns 409.
        """
        # Reject if already accepted
        result = await db.execute(
            select(TrustedDevice).where(
                TrustedDevice.owner_user_id == owner_user_id,
                TrustedDevice.device_fingerprint == device_fingerprint,
                TrustedDevice.status == "accepted",
            )
        )
        if result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Device is already trusted",
            )

        code = TrustedDeviceService._generate_pairing_code()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=PAIRING_CODE_TTL_MINUTES)

        pairing = DevicePairing(
            owner_user_id=owner_user_id,
            device_fingerprint=device_fingerprint,
            friendly_name=friendly_name,
            device_platform=device_platform,
            pairing_code_hash=_sha256(code),
            status="pending",
            expires_at=expires_at,
        )
        db.add(pairing)
        await db.commit()
        await db.refresh(pairing)
        return pairing.id, code, expires_at

    @staticmethod
    async def confirm_pairing(
        owner_user_id: str,
        pairing_code: str,
        password: str,
        db: AsyncSession,
    ) -> TrustedDevice:
        """Confirm a pending pairing by code + owner password.

        The password re-authentication proves the physical owner is present
        before a new device is granted helper access.
        """
        # 1. Verify the owner's password (list is password protected)
        result = await db.execute(select(User).where(User.id == owner_user_id))
        user = result.scalar_one_or_none()
        if user is None or not verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid password — device list is password protected",
            )

        # 2. Find the matching pending pairing
        result = await db.execute(
            select(DevicePairing).where(
                DevicePairing.owner_user_id == owner_user_id,
                DevicePairing.status == "pending",
            )
        )
        pairings = result.scalars().all()
        code_hash = _sha256(pairing_code)
        pairing = next(
            (p for p in pairings if secrets.compare_digest(p.pairing_code_hash, code_hash)),
            None,
        )

        if pairing is None:
            for p in pairings:
                p.failed_attempts += 1
                if p.failed_attempts >= 5:
                    p.status = "expired"
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pairing code not found",
            )

        # 3. Check expiry and attempt limits
        if pairing.failed_attempts >= 5 or _is_expired(pairing.expires_at):
            pairing.status = "expired"
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Pairing code has expired or was locked due to too many attempts",
            )

        # 4. Create the accepted device
        device = TrustedDevice(
            owner_user_id=owner_user_id,
            device_fingerprint=pairing.device_fingerprint,
            friendly_name=pairing.friendly_name,
            device_platform=pairing.device_platform,
            status="accepted",
        )
        db.add(device)
        pairing.status = "confirmed"
        await db.commit()
        await db.refresh(device)
        return device

    @staticmethod
    async def generate_setup_code(
        owner_user_id: str,
        db: AsyncSession,
    ) -> tuple[str, str, datetime]:
        """Issue a setup code the owner reads aloud to their helper.

        Unlike the legacy device-initiated flow, this creates a pairing that
        has no device attached yet — the helper will claim it by entering the
        code on their own device.
        """
        code = TrustedDeviceService._generate_pairing_code()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=PAIRING_CODE_TTL_MINUTES)

        pairing = DevicePairing(
            owner_user_id=owner_user_id,
            device_fingerprint="",
            friendly_name=None,
            device_platform=None,
            pairing_code_hash=_sha256(code),
            status="awaiting_helper",
            expires_at=expires_at,
        )
        db.add(pairing)
        await db.commit()
        await db.refresh(pairing)
        return pairing.id, code, expires_at

    @staticmethod
    async def claim_setup_code(
        setup_code: str,
        device_fingerprint: str,
        friendly_name: str | None,
        device_platform: str | None,
        claimer_user_id: str,
        db: AsyncSession,
    ) -> DevicePairing:
        """Bind the helper's device to a pairing using the code read aloud.

        The pairing is moved to 'pending', awaiting the owner's one-tap
        approval. A device already trusted by that owner cannot re-claim.
        """
        result = await db.execute(
            select(DevicePairing).where(
                DevicePairing.status == "awaiting_helper",
            )
        )
        candidates = result.scalars().all()
        code_hash = _sha256(setup_code)
        pairing = next(
            (p for p in candidates if secrets.compare_digest(p.pairing_code_hash, code_hash)),
            None,
        )
        if pairing is None:
            for cand in candidates:
                cand.failed_attempts += 1
                if cand.failed_attempts >= 5:
                    cand.status = "expired"
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Setup code not found",
            )

        if pairing.failed_attempts >= 5 or _is_expired(pairing.expires_at):
            pairing.status = "expired"
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Setup code has expired or was locked due to too many attempts",
            )

        # Reject if this device is already accepted for the owner
        result = await db.execute(
            select(TrustedDevice).where(
                TrustedDevice.owner_user_id == pairing.owner_user_id,
                TrustedDevice.device_fingerprint == device_fingerprint,
                TrustedDevice.status == "accepted",
            )
        )
        if result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Device is already trusted",
            )

        pairing.device_fingerprint = device_fingerprint
        pairing.friendly_name = friendly_name
        pairing.device_platform = device_platform
        # Remember WHO claimed it — this makes trust mutual: the owner's list
        # gains a contact card, and the helper's "people I help" list gains
        # the owner.
        pairing.claimed_by_user_id = claimer_user_id
        pairing.status = "pending"
        await db.commit()
        await db.refresh(pairing)
        return pairing

    @staticmethod
    async def list_pending_pairings(
        owner_user_id: str,
        db: AsyncSession,
    ) -> list[DevicePairing]:
        """Return pairings awaiting the owner's one-tap approval."""
        result = await db.execute(
            select(DevicePairing)
            .where(
                DevicePairing.owner_user_id == owner_user_id,
                DevicePairing.status == "pending",
            )
            .order_by(DevicePairing.created_at.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def approve_pairing(
        owner_user_id: str,
        pairing_id: str,
        db: AsyncSession,
    ) -> TrustedDevice:
        """Owner approves a claimed pairing with one tap — no password.

        The pairing code (read aloud to the helper) plus this one-tap approval
        on the owner's own device is the consent. This keeps the elderly side
        dead simple.
        """
        result = await db.execute(
            select(DevicePairing).where(
                DevicePairing.id == pairing_id,
                DevicePairing.owner_user_id == owner_user_id,
                DevicePairing.status == "pending",
            )
        )
        pairing = result.scalar_one_or_none()
        if pairing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pending pairing not found",
            )

        if _is_expired(pairing.expires_at):
            pairing.status = "expired"
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Pairing has expired",
            )

        # Check if an existing TrustedDevice row exists for (owner_user_id, pairing.device_fingerprint)
        res_existing = await db.execute(
            select(TrustedDevice).where(
                TrustedDevice.owner_user_id == owner_user_id,
                TrustedDevice.device_fingerprint == pairing.device_fingerprint,
            )
        )
        device = res_existing.scalar_one_or_none()
        if device is not None:
            device.helper_user_id = pairing.claimed_by_user_id
            device.friendly_name = pairing.friendly_name
            device.device_platform = pairing.device_platform
            device.status = "accepted"
        else:
            device = TrustedDevice(
                owner_user_id=owner_user_id,
                device_fingerprint=pairing.device_fingerprint,
                helper_user_id=pairing.claimed_by_user_id,
                friendly_name=pairing.friendly_name,
                device_platform=pairing.device_platform,
                status="accepted",
            )
            db.add(device)

        pairing.status = "confirmed"
        await db.commit()
        await db.refresh(device)
        return device

    @staticmethod
    async def list_helping(helper_user_id: str, db: AsyncSession) -> list[dict]:
        """The helper's address book: people this user has been trusted to help.

        Derived from accepted trust rows where THIS user claimed the device —
        the mutual side of the owner's trusted list.
        """
        result = await db.execute(
            select(TrustedDevice)
            .where(
                TrustedDevice.helper_user_id == helper_user_id,
                TrustedDevice.status == "accepted",
            )
            .order_by(TrustedDevice.created_at.desc())
        )
        rows = result.scalars().all()

        entries: list[dict] = []
        for row in rows:
            res = await db.execute(select(User).where(User.id == row.owner_user_id))
            owner = res.scalar_one_or_none()
            entries.append(
                {
                    "device_id": row.id,
                    "owner_user_id": row.owner_user_id,
                    "helper_user_id": row.helper_user_id,
                    "device_fingerprint": row.device_fingerprint,
                    "owner_display_name": (owner.display_name if owner else None),
                    "friendly_name": row.friendly_name,
                    "device_tag": row.id.replace("-", "")[:6].upper(),
                    "since": row.created_at,
                }
            )
        return entries

    # ------------------------------------------------------------------
    # List / manage (password protected)
    # ------------------------------------------------------------------

    @staticmethod
    async def list_devices(owner_user_id: str, db: AsyncSession) -> list[TrustedDevice]:
        """List all trusted devices for a user (accepted only)."""
        result = await db.execute(
            select(TrustedDevice)
            .where(
                TrustedDevice.owner_user_id == owner_user_id,
                TrustedDevice.status == "accepted",
            )
            .order_by(TrustedDevice.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def revoke_device(
        owner_user_id: str,
        device_id: str,
        db: AsyncSession,
    ) -> None:
        """Revoke a trusted device (owner's one-tap consent, no password).

        The pairing flow (setup code + one-tap approval on the owner's own
        device) is the consent gate; revocation is equally protected by the
        physical device being present.
        """
        result = await db.execute(
            select(TrustedDevice).where(
                TrustedDevice.id == device_id,
                TrustedDevice.owner_user_id == owner_user_id,
            )
        )
        device = result.scalar_one_or_none()
        if device is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Trusted device not found",
            )

        device.status = "revoked"
        await db.commit()

    @staticmethod
    async def verify_device_identity(
        owner_user_id: str,
        device_fingerprint: str,
        db: AsyncSession,
    ) -> dict:
        """Check whether a given device is trusted to assist this user."""
        result = await db.execute(
            select(TrustedDevice).where(
                TrustedDevice.owner_user_id == owner_user_id,
                TrustedDevice.device_fingerprint == device_fingerprint,
            )
        )
        device = result.scalar_one_or_none()

        if device is None or device.status != "accepted":
            return {
                "is_trusted": False,
                "status": device.status if device else "unknown",
                "device_id": None,
                "friendly_name": None,
            }

        return {
            "is_trusted": True,
            "status": "accepted",
            "device_id": device.id,
            "friendly_name": device.friendly_name,
        }
