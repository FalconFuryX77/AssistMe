"""Voice communication business logic."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.session import Session
from models.session_participant import SessionParticipant


class VoiceService:
    """Manages audio call state, mute toggles, audio routing, and quality degradation adaptation."""

    @staticmethod
    async def start_audio_call(
        session_id: str,
        user_id: str,
        is_muted: bool,
        audio_route: str,
        db: AsyncSession,
    ) -> SessionParticipant:
        """Start audio call participation for a user in a session."""
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
                detail="Must be connected to join audio call",
            )

        participant.is_in_audio_call = True
        participant.is_audio_muted = is_muted
        participant.audio_route = audio_route
        participant.audio_quality = "high"

        await db.commit()
        await db.refresh(participant)
        return participant

    @staticmethod
    async def stop_audio_call(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> SessionParticipant:
        """Stop audio call participation for a user."""
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

        participant.is_in_audio_call = False
        participant.is_audio_muted = False

        await db.commit()
        await db.refresh(participant)
        return participant

    @staticmethod
    async def toggle_mute(
        session_id: str,
        user_id: str,
        is_muted: bool,
        db: AsyncSession,
    ) -> SessionParticipant:
        """Toggle mute state for a user in an active audio call."""
        result = await db.execute(
            select(SessionParticipant).where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.user_id == user_id,
            )
        )
        participant = result.scalar_one_or_none()

        if participant is None or not participant.is_in_audio_call:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User is not currently in an active audio call",
            )

        participant.is_audio_muted = is_muted
        await db.commit()
        await db.refresh(participant)
        return participant

    @staticmethod
    async def change_audio_route(
        session_id: str,
        user_id: str,
        audio_route: str,
        db: AsyncSession,
    ) -> SessionParticipant:
        """Change audio output routing (speaker, earpiece, bluetooth, headset)."""
        result = await db.execute(
            select(SessionParticipant).where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.user_id == user_id,
            )
        )
        participant = result.scalar_one_or_none()

        if participant is None or not participant.is_in_audio_call:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User is not currently in an active audio call",
            )

        participant.audio_route = audio_route
        await db.commit()
        await db.refresh(participant)
        return participant

    @staticmethod
    async def report_degradation(
        session_id: str,
        user_id: str,
        quality_level: str,
        packet_loss: float | None,
        db: AsyncSession,
    ) -> SessionParticipant:
        """Report network degradation and adapt audio quality level."""
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

        participant.audio_quality = quality_level
        await db.commit()
        await db.refresh(participant)
        return participant

    @staticmethod
    async def get_audio_status(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> dict:
        """Get active audio call status for the session."""
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

        active_audio = next(
            (p for p in session.participants if p.user_id == user_id), None
        )

        if active_audio:
            return {
                "is_in_audio_call": active_audio.is_in_audio_call,
                "is_audio_muted": active_audio.is_audio_muted,
                "audio_route": active_audio.audio_route,
                "audio_quality": active_audio.audio_quality,
                "participant_user_id": active_audio.user_id,
            }
        else:
            return {
                "is_in_audio_call": False,
                "is_audio_muted": False,
                "audio_route": "speaker",
                "audio_quality": "high",
                "participant_user_id": None,
            }
