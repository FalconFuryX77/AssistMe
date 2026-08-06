"""Session Recording & Audit Trail Service."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.audit_log import AuditLog
from models.session import Session
from models.session_participant import SessionParticipant


class AuditRecordingService:
    """Manages session recording consent, recording lifecycle, and privacy compliance audit logging."""

    @staticmethod
    async def log_audit_event(
        session_id: str,
        user_id: str | None,
        event_type: str,
        detail: str | None,
        db: AsyncSession,
    ) -> AuditLog:
        """Helper to create a structured audit log entry."""
        audit_entry = AuditLog(
            session_id=session_id,
            user_id=user_id,
            event_type=event_type,
            detail=detail,
        )
        db.add(audit_entry)
        await db.commit()
        await db.refresh(audit_entry)
        return audit_entry

    @staticmethod
    async def update_consent(
        session_id: str,
        user_id: str,
        consent_granted: bool,
        recording_scope: str,
        db: AsyncSession,
    ) -> Session:
        """Update session recording consent."""
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

        session.recording_consent_granted = consent_granted
        session.recording_scope = recording_scope

        # Log audit event
        audit_entry = AuditLog(
            session_id=session.id,
            user_id=user_id,
            event_type="recording_consent_updated",
            detail=f"Consent: {consent_granted}, Scope: {recording_scope}",
        )
        db.add(audit_entry)

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
    async def start_recording(
        session_id: str,
        user_id: str,
        storage_provider: str,
        db: AsyncSession,
    ) -> Session:
        """Start session recording stream (requires recording_consent_granted == True)."""
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

        if not session.recording_consent_granted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Recording consent has not been granted by session participants",
            )

        session.is_recording = True

        audit_entry = AuditLog(
            session_id=session.id,
            user_id=user_id,
            event_type="recording_started",
            detail=f"Provider: {storage_provider}",
        )
        db.add(audit_entry)

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
    async def stop_recording(
        session_id: str,
        user_id: str,
        file_url: str,
        file_size_bytes: int,
        duration_seconds: int,
        db: AsyncSession,
    ) -> Session:
        """Stop active session recording and save file metadata."""
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

        session.is_recording = False
        session.recording_url = file_url
        session.recording_file_size_bytes = file_size_bytes
        session.recording_duration_seconds = duration_seconds

        audit_entry = AuditLog(
            session_id=session.id,
            user_id=user_id,
            event_type="recording_stopped",
            detail=f"File: {file_url}, Size: {file_size_bytes}B, Duration: {duration_seconds}s",
        )
        db.add(audit_entry)

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
    async def get_recording_status(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> dict:
        """Get current recording status and file metadata."""
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
            "is_recording": session.is_recording,
            "consent_granted": session.recording_consent_granted,
            "recording_scope": session.recording_scope,
            "recording_url": session.recording_url,
            "file_size_bytes": session.recording_file_size_bytes,
            "duration_seconds": session.recording_duration_seconds,
        }

    @staticmethod
    async def get_audit_trail(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> dict:
        """Retrieve structured audit logs for a session."""
        result = await db.execute(
            select(AuditLog)
            .where(AuditLog.session_id == session_id)
            .order_by(AuditLog.timestamp.asc())
        )
        logs = result.scalars().all()

        return {
            "session_id": session_id,
            "total_events": len(logs),
            "events": logs,
        }
