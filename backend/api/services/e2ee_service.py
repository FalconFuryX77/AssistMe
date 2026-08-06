"""End-to-End Encryption (E2EE) Signal Protocol key exchange and MITM verification service."""

import hashlib
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.session import Session
from models.session_participant import SessionParticipant


class E2EEService:
    """Manages E2EE key exchange, SHA-256 SAS fingerprint derivation, key rotation, and MITM security checks."""

    @staticmethod
    def _derive_fingerprint(identity_key: str, signed_prekey: str) -> str:
        """Derive a 64-character SHA-256 safety number fingerprint from key parameters."""
        raw = f"{identity_key}:{signed_prekey}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    async def exchange_keys(
        session_id: str,
        user_id: str,
        identity_key: str,
        signed_prekey: str,
        ephemeral_key: str,
        algorithm: str,
        db: AsyncSession,
    ) -> Session:
        """Exchange E2EE identity keys and prekeys for WebRTC Insertable Streams."""
        result = await db.execute(
            select(Session)
            .where(Session.id == session_id)
            .options(selectinload(Session.participants))
        )
        session = result.scalar_one_or_none()

        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )

        participant = next(
            (p for p in session.participants if p.user_id == user_id), None
        )
        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a participant of this session",
            )

        fingerprint = E2EEService._derive_fingerprint(identity_key, signed_prekey)
        session.e2ee_enabled = True
        session.e2ee_key_exchange_complete = True
        session.e2ee_fingerprint = fingerprint

        session_id_val = session.id
        await db.commit()

        res = await db.execute(
            select(Session)
            .where(Session.id == session_id_val)
            .options(selectinload(Session.participants))
            .execution_options(populate_existing=True)
        )
        return res.scalar_one()

    @staticmethod
    async def rotate_keys(
        session_id: str,
        user_id: str,
        new_ephemeral_key: str,
        ratchet_counter: int,
        db: AsyncSession,
    ) -> Session:
        """Rotate Double Ratchet ephemeral keys for forward secrecy."""
        result = await db.execute(
            select(Session)
            .where(Session.id == session_id)
            .options(selectinload(Session.participants))
        )
        session = result.scalar_one_or_none()

        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )

        if not session.e2ee_key_exchange_complete:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Key exchange must be completed before performing key rotation",
            )

        session_id_val = session.id
        await db.commit()

        res = await db.execute(
            select(Session)
            .where(Session.id == session_id_val)
            .options(selectinload(Session.participants))
            .execution_options(populate_existing=True)
        )
        return res.scalar_one()

    @staticmethod
    async def verify_fingerprint(
        session_id: str,
        user_id: str,
        safety_number_fingerprint: str,
        is_verified_by_user: bool,
        db: AsyncSession,
    ) -> Session:
        """Verify SAS fingerprint to prevent Man-In-The-Middle (MITM) attacks."""
        result = await db.execute(
            select(Session)
            .where(Session.id == session_id)
            .options(selectinload(Session.participants))
        )
        session = result.scalar_one_or_none()

        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )

        if not session.e2ee_key_exchange_complete or not session.e2ee_fingerprint:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active E2EE key exchange fingerprint to verify",
            )

        if safety_number_fingerprint.lower() != session.e2ee_fingerprint.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Security fingerprint mismatch! Potential Man-In-The-Middle attack detected.",
            )

        session.e2ee_mitm_verified = is_verified_by_user

        session_id_val = session.id
        await db.commit()

        res = await db.execute(
            select(Session)
            .where(Session.id == session_id_val)
            .options(selectinload(Session.participants))
            .execution_options(populate_existing=True)
        )
        return res.scalar_one()

    @staticmethod
    async def get_status(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> dict:
        """Get E2EE status and security fingerprint."""
        result = await db.execute(
            select(Session)
            .where(Session.id == session_id)
            .options(selectinload(Session.participants))
        )
        session = result.scalar_one_or_none()

        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )

        return {
            "session_id": session.id,
            "e2ee_enabled": session.e2ee_enabled,
            "key_exchange_complete": session.e2ee_key_exchange_complete,
            "fingerprint": session.e2ee_fingerprint,
            "is_mitm_verified": session.e2ee_mitm_verified,
        }
