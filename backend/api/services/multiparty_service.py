"""Multi-party Assistance Sessions business logic and role management service."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.session import Session
from models.session_participant import SessionParticipant
from models.user import User


class MultiPartyService:
    """Manages multi-helper invitation workflows, RBAC role updates, and active speaker layout switching."""

    @staticmethod
    async def invite_participant(
        session_id: str,
        current_user_id: str,
        email_or_user_id: str,
        role: str,
        db: AsyncSession,
    ) -> SessionParticipant:
        """Invite a secondary helper or observer to an active session."""
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

        # Creator / primary_helper check
        if session.creator_id != current_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the session creator/primary helper can invite participants",
            )

        # Find target user by ID or email
        u_result = await db.execute(
            select(User).where(
                (User.id == email_or_user_id) | (User.email == email_or_user_id)
            )
        )
        target_user = u_result.scalar_one_or_none()

        if target_user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User '{email_or_user_id}' not found",
            )

        # Check if already participant
        existing = next(
            (p for p in session.participants if p.user_id == target_user.id), None
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User is already a participant of this session",
            )

        participant = SessionParticipant(
            session_id=session.id,
            user_id=target_user.id,
            role=role,
            status="connected",
        )
        db.add(participant)
        await db.commit()
        await db.refresh(participant)
        return participant

    @staticmethod
    async def update_participant_role(
        session_id: str,
        current_user_id: str,
        target_participant_id: str,
        new_role: str,
        db: AsyncSession,
    ) -> SessionParticipant:
        """Update a participant's role in a session."""
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

        if session.creator_id != current_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the session creator can update participant roles",
            )

        target_participant = next(
            (p for p in session.participants if p.id == target_participant_id), None
        )
        if target_participant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Participant not found in session",
            )

        target_participant.role = new_role
        await db.commit()
        await db.refresh(target_participant)
        return target_participant

    @staticmethod
    async def set_active_speaker(
        session_id: str,
        current_user_id: str,
        active_speaker_user_id: str,
        audio_level_db: float | None,
        db: AsyncSession,
    ) -> dict:
        """Set active speaker for multi-stream video layout routing."""
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

        for p in session.participants:
            p.is_active_speaker = (p.user_id == active_speaker_user_id)

        await db.commit()
        return {
            "session_id": session.id,
            "active_speaker_user_id": active_speaker_user_id,
            "audio_level_db": audio_level_db or 0.0,
        }

    @staticmethod
    async def get_participants(
        session_id: str,
        current_user_id: str,
        db: AsyncSession,
    ) -> dict:
        """Get all participants in a multi-party session."""
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
            "total_participants": len(session.participants),
            "participants": session.participants,
        }
