"""Remote Control Protocol business logic and security permission enforcement."""

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.schemas.remote_control import RemoteControlInputEvent
from models.session import Session
from models.session_participant import SessionParticipant


class RemoteControlService:
    """Enforces explicit permission checks and input gesture routing."""

    @staticmethod
    async def grant_remote_control(
        session_id: str,
        user_id: str,
        platform: str,
        db: AsyncSession,
    ) -> Session:
        """Grant remote control permission to the helper in an active session."""
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

        if session.status != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Remote control can only be granted in an active session",
            )

        # Verify user is a participant
        participant = next(
            (p for p in session.participants if p.user_id == user_id), None
        )
        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a participant of this session",
            )

        session.remote_control_granted = True
        session.remote_control_granted_at = datetime.now(timezone.utc)
        session.remote_control_platform = platform

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
    async def revoke_remote_control(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> Session:
        """Instantly revoke remote control permission."""
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

        session.remote_control_granted = False
        session.remote_control_granted_at = None

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
    async def dispatch_input_event(
        session_id: str,
        user_id: str,
        input_event: RemoteControlInputEvent,
        db: AsyncSession,
    ) -> dict:
        """Dispatch a remote gesture/key input event.

        Requires remote_control_granted == True.
        """
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

        if not session.remote_control_granted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Remote control permission has not been granted by the helpee",
            )

        # Verify sender is a participant
        participant = next(
            (p for p in session.participants if p.user_id == user_id), None
        )
        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a participant of this session",
            )

        return {
            "session_id": session.id,
            "sender_user_id": user_id,
            "platform": session.remote_control_platform,
            "event": input_event.model_dump(),
        }

    @staticmethod
    async def get_status(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> dict:
        """Get current remote control permission status."""
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
            "remote_control_granted": session.remote_control_granted,
            "remote_control_granted_at": session.remote_control_granted_at,
            "remote_control_platform": session.remote_control_platform,
        }
