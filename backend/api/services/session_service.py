"""Session management business logic."""

import secrets
import string
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.session import Session
from models.session_participant import SessionParticipant
from models.user import User


def _generate_session_code(length: int = 6) -> str:
    """Generate a short, human-friendly session code (uppercase + digits)."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class SessionService:
    """Manages assistance session lifecycle."""

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    @staticmethod
    async def create_session(
        creator_id: str,
        title: str | None,
        timeout_minutes: int,
        db: AsyncSession,
    ) -> Session:
        """Create a new session and add the creator as 'helper'.

        Generates a unique session code for the helpee to join.
        """
        # Generate a unique session code (retry on collision)
        for _ in range(10):
            code = _generate_session_code()
            result = await db.execute(
                select(Session).where(Session.session_code == code)
            )
            if result.scalar_one_or_none() is None:
                break
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate unique session code",
            )

        session = Session(
            creator_id=creator_id,
            title=title,
            session_code=code,
            timeout_minutes=timeout_minutes,
        )
        db.add(session)
        await db.flush()

        # Add creator as the helper participant
        participant = SessionParticipant(
            session_id=session.id,
            user_id=creator_id,
            role="helper",
            status="connected",
        )
        db.add(participant)
        await db.commit()

        # Reload with participants
        result = await db.execute(
            select(Session)
            .where(Session.id == session.id)
            .options(selectinload(Session.participants))
        )
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Join
    # ------------------------------------------------------------------

    @staticmethod
    async def join_session(
        session_code: str,
        user_id: str,
        db: AsyncSession,
    ) -> Session:
        """Join an existing session by its code.

        Raises:
            404 – session not found or already ended
            400 – duplicate join
        """
        result = await db.execute(
            select(Session)
            .where(Session.session_code == session_code)
            .options(selectinload(Session.participants))
        )
        session = result.scalar_one_or_none()

        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )

        if session.status == "ended":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session has already ended",
            )

        # Check for duplicate (or reconnection)
        existing = next(
            (p for p in session.participants if p.user_id == user_id), None
        )

        if existing is not None:
            if existing.status == "disconnected":
                # Reconnect — recovery path
                existing.status = "connected"
                existing.last_seen_at = datetime.now(timezone.utc)
                existing.left_at = None
                await db.commit()
                await db.refresh(session)
                return session
            elif existing.status == "connected":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Already connected to this session",
                )
            else:
                # Was 'left' — rejoin
                existing.status = "connected"
                existing.last_seen_at = datetime.now(timezone.utc)
                existing.left_at = None
                await db.commit()
                await db.refresh(session)
                return session

        # New participant joins as helpee
        participant = SessionParticipant(
            session_id=session.id,
            user_id=user_id,
            role="helpee",
            status="connected",
        )
        db.add(participant)

        # Transition session to active if it was waiting
        if session.status == "waiting":
            session.status = "active"

        await db.commit()

        # Expire cached state and reload with updated participants
        db.expire_all()
        result = await db.execute(
            select(Session)
            .where(Session.id == session.id)
            .options(selectinload(Session.participants))
        )
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Leave
    # ------------------------------------------------------------------

    @staticmethod
    async def leave_session(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> Session:
        """Leave a session voluntarily.

        If the creator (helper) leaves, the session ends.
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

        if session.status == "ended":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session has already ended",
            )

        participant = next(
            (p for p in session.participants if p.user_id == user_id), None
        )

        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Not a participant of this session",
            )

        now = datetime.now(timezone.utc)
        participant.status = "left"
        participant.left_at = now

        # If the helper leaves, end the session
        if session.creator_id == user_id:
            session.status = "ended"
            session.ended_at = now
            # Mark all remaining participants as left
            for p in session.participants:
                if p.status == "connected":
                    p.status = "left"
                    p.left_at = now

        await db.commit()

        result = await db.execute(
            select(Session)
            .where(Session.id == session.id)
            .options(selectinload(Session.participants))
        )
        return result.scalar_one()

    # ------------------------------------------------------------------
    # End session
    # ------------------------------------------------------------------

    @staticmethod
    async def end_session(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> Session:
        """Explicitly end a session. Only the creator can end it."""
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

        if session.creator_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the session creator can end the session",
            )

        if session.status == "ended":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session has already ended",
            )

        now = datetime.now(timezone.utc)
        session.status = "ended"
        session.ended_at = now

        for p in session.participants:
            if p.status == "connected":
                p.status = "left"
                p.left_at = now

        await db.commit()

        result = await db.execute(
            select(Session)
            .where(Session.id == session.id)
            .options(selectinload(Session.participants))
        )
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Recovery (mark as disconnected / reconnect)
    # ------------------------------------------------------------------

    @staticmethod
    async def mark_disconnected(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> None:
        """Mark a participant as disconnected (e.g. network loss).

        Called internally when a WebSocket drops.
        """
        result = await db.execute(
            select(SessionParticipant).where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.user_id == user_id,
            )
        )
        participant = result.scalar_one_or_none()

        if participant and participant.status == "connected":
            participant.status = "disconnected"
            await db.commit()

    @staticmethod
    async def recover_session(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> Session:
        """Reconnect to a session after disconnection.

        Raises:
            404 – session not found
            400 – session ended or user not a disconnected participant
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

        if session.status == "ended":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session has already ended",
            )

        participant = next(
            (p for p in session.participants if p.user_id == user_id), None
        )

        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Not a participant of this session",
            )

        if participant.status != "disconnected":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Not in a disconnected state",
            )

        participant.status = "connected"
        participant.last_seen_at = datetime.now(timezone.utc)
        participant.left_at = None
        await db.commit()

        result = await db.execute(
            select(Session)
            .where(Session.id == session.id)
            .options(selectinload(Session.participants))
        )
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Get / List
    # ------------------------------------------------------------------

    @staticmethod
    async def get_session(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> Session:
        """Get a session by ID. Only participants can view."""
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

        # Verify user is a participant
        is_participant = any(p.user_id == user_id for p in session.participants)
        if not is_participant:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a participant of this session",
            )

        return session

    @staticmethod
    async def list_sessions(
        user_id: str,
        status_filter: str | None,
        db: AsyncSession,
    ) -> list[dict]:
        """List sessions the user is a participant of."""
        query = (
            select(Session)
            .join(SessionParticipant)
            .where(SessionParticipant.user_id == user_id)
            .options(selectinload(Session.participants))
        )
        if status_filter:
            query = query.where(Session.status == status_filter)

        query = query.order_by(Session.created_at.desc())
        result = await db.execute(query)
        sessions = result.scalars().unique().all()

        return [
            {
                "id": s.id,
                "status": s.status,
                "title": s.title,
                "session_code": s.session_code,
                "created_at": s.created_at,
                "participant_count": len(s.participants),
            }
            for s in sessions
        ]

    # ------------------------------------------------------------------
    # Timeout check
    # ------------------------------------------------------------------

    @staticmethod
    async def check_and_expire_sessions(db: AsyncSession) -> int:
        """Expire sessions that have exceeded their timeout.

        Returns the number of sessions expired.
        """
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(Session)
            .where(Session.status.in_(["waiting", "active"]))
            .options(selectinload(Session.participants))
        )
        sessions = result.scalars().all()

        expired_count = 0
        for session in sessions:
            timeout_delta = timedelta(minutes=session.timeout_minutes)
            if session.created_at.replace(tzinfo=timezone.utc) + timeout_delta < now:
                session.status = "ended"
                session.ended_at = now
                for p in session.participants:
                    if p.status in ("connected", "disconnected"):
                        p.status = "left"
                        p.left_at = now
                expired_count += 1

        if expired_count > 0:
            await db.commit()

        return expired_count

    # ------------------------------------------------------------------
    # Heartbeat (keep-alive)
    # ------------------------------------------------------------------

    @staticmethod
    async def heartbeat(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> None:
        """Update the last_seen_at for a participant (keep-alive)."""
        result = await db.execute(
            select(SessionParticipant).where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.user_id == user_id,
                SessionParticipant.status == "connected",
            )
        )
        participant = result.scalar_one_or_none()

        if participant:
            participant.last_seen_at = datetime.now(timezone.utc)
            await db.commit()
