"""Screen sharing business logic."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.session import Session
from models.session_participant import SessionParticipant


class ScreenShareService:
    """Manages screen sharing session state and security event transitions."""

    @staticmethod
    async def start_screen_share(
        session_id: str,
        user_id: str,
        platform: str,
        orientation: str,
        db: AsyncSession,
    ) -> SessionParticipant:
        """Start screen sharing for a participant in an active session."""
        result = await db.execute(
            select(SessionParticipant).where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.user_id == user_id,
            )
        )
        participant = result.scalar_one_or_none()

        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Participant not found in session",
            )

        if participant.status != "connected":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Must be connected to start screen sharing",
            )

        participant.is_screen_sharing = True
        participant.screen_share_platform = platform
        participant.screen_orientation = orientation
        participant.is_flag_secure_active = False

        await db.commit()
        await db.refresh(participant)
        return participant

    @staticmethod
    async def stop_screen_share(
        session_id: str,
        user_id: str,
        reason: str | None,
        db: AsyncSession,
    ) -> SessionParticipant:
        """Stop screen sharing for a participant."""
        result = await db.execute(
            select(SessionParticipant).where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.user_id == user_id,
            )
        )
        participant = result.scalar_one_or_none()

        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Participant not found in session",
            )

        participant.is_screen_sharing = False
        participant.screen_share_platform = None
        participant.is_flag_secure_active = False

        await db.commit()
        await db.refresh(participant)
        return participant

    @staticmethod
    async def update_orientation(
        session_id: str,
        user_id: str,
        orientation: str,
        db: AsyncSession,
    ) -> SessionParticipant:
        """Update screen share orientation (portrait / landscape)."""
        result = await db.execute(
            select(SessionParticipant).where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.user_id == user_id,
            )
        )
        participant = result.scalar_one_or_none()

        if participant is None or not participant.is_screen_sharing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Screen sharing is not currently active",
            )

        participant.screen_orientation = orientation
        await db.commit()
        await db.refresh(participant)
        return participant

    @staticmethod
    async def handle_security_event(
        session_id: str,
        user_id: str,
        event_type: str,
        detail: str | None,
        db: AsyncSession,
    ) -> SessionParticipant:
        """Handle security and protection events (FLAG_SECURE, protected apps, backgrounding)."""
        result = await db.execute(
            select(SessionParticipant).where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.user_id == user_id,
            )
        )
        participant = result.scalar_one_or_none()

        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Participant not found in session",
            )

        if event_type in ("flag_secure_enabled", "protected_app_entered"):
            participant.is_flag_secure_active = True
        elif event_type in ("flag_secure_disabled", "protected_app_exited"):
            participant.is_flag_secure_active = False

        await db.commit()
        await db.refresh(participant)
        return participant

    @staticmethod
    async def get_status(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> dict:
        """Get current screen share status for a session."""
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

        active_sharing = next(
            (p for p in session.participants if p.is_screen_sharing), None
        )

        if active_sharing:
            return {
                "is_screen_sharing": True,
                "platform": active_sharing.screen_share_platform,
                "is_flag_secure_active": active_sharing.is_flag_secure_active,
                "screen_orientation": active_sharing.screen_orientation,
                "participant_user_id": active_sharing.user_id,
            }
        else:
            return {
                "is_screen_sharing": False,
                "platform": None,
                "is_flag_secure_active": False,
                "screen_orientation": "portrait",
                "participant_user_id": None,
            }
