"""Context Engine business logic (Phase 8).

Detects and persists per-participant device & session context: platform,
foreground app, accessibility state, permissions, screen sharing / security
state, and session state. Provides classification helpers (e.g. sensitive-app
detection) consumed by the Adaptive Policy Engine.
"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.schemas.context_engine import ContextReportRequest
from models.context_snapshot import ContextSnapshot
from models.session import Session
from models.session_participant import SessionParticipant

# Known sensitive app categories that should never be controlled/annotated
# while active. Extendable over time.
_SENSITIVE_CATEGORIES: frozenset[str] = frozenset(
    {
        "banking",
        "health",
        "password_manager",
        "payment",
        "ecommerce",
        "government",
    }
)

# Package-name -> category heuristics for common sensitive apps.
_APP_CATEGORY_HINTS: dict[str, str] = {
    "com.android.settings": "system",
    "com.android.systemui": "system",
    "com.android.bank": "banking",
    "com.americanexpress.android": "banking",
    "com.chase.smartphone": "banking",
    "com.wellsfargo.bank": "banking",
    "com.paypal.android.p2pmobile": "payment",
    "com.google.android.apps.walletnfcrel": "payment",
}


class ContextEngineService:
    """Collects, persists, and classifies participant context."""

    @staticmethod
    async def report_context(
        session_id: str,
        user_id: str,
        report: ContextReportRequest,
        db: AsyncSession,
    ) -> ContextSnapshot:
        """Upsert the latest context snapshot for a participant.

        Derives platform + screen values from the report, computes sensitive-app
        status, and enriches the snapshot with authoritative session state.
        """
        session = await ContextEngineService._load_session(session_id, user_id, db)

        participant = next(
            (p for p in session.participants if p.user_id == user_id), None
        )
        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a participant of this session",
            )

        result = await db.execute(
            select(ContextSnapshot).where(
                ContextSnapshot.session_id == session_id,
                ContextSnapshot.user_id == user_id,
            )
        )
        snapshot = result.scalar_one_or_none()

        if snapshot is None:
            snapshot = ContextSnapshot(
                session_id=session_id,
                user_id=user_id,
                platform=report.platform or "unknown",
            )
            db.add(snapshot)

        fields = report.model_dump(exclude_unset=True)
        for key, value in fields.items():
            setattr(snapshot, key, value)

        # Derive sensitive-app classification from reported category / app hints.
        category = report.foreground_app_category
        app = report.foreground_app
        if report.is_sensitive_app is not None:
            snapshot.is_sensitive_app = report.is_sensitive_app
        else:
            if category is not None:
                snapshot.is_sensitive_app = (
                    category.lower() in _SENSITIVE_CATEGORIES
                )
            elif app is not None:
                hint = _APP_CATEGORY_HINTS.get(app)
                snapshot.is_sensitive_app = (
                    hint in _SENSITIVE_CATEGORIES if hint else False
                )
            snapshot.foreground_app_category = category

        # Enrich with authoritative session state.
        snapshot.role = participant.role
        snapshot.session_status = session.status

        # Keep participant streaming/security flags in sync with the report so
        # the snapshot and session state stay consistent.
        if report.is_screen_sharing is not None:
            participant.is_screen_sharing = report.is_screen_sharing
        if report.is_flag_secure_active is not None:
            participant.is_flag_secure_active = report.is_flag_secure_active
        if report.is_in_audio_call is not None:
            participant.is_in_audio_call = report.is_in_audio_call

        snapshot.is_screen_sharing = participant.is_screen_sharing
        snapshot.is_flag_secure_active = participant.is_flag_secure_active
        snapshot.is_in_audio_call = participant.is_in_audio_call

        await db.commit()
        await db.refresh(snapshot)
        return snapshot

    @staticmethod
    async def get_context(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> ContextSnapshot:
        """Return the current participant's context snapshot."""
        await ContextEngineService._load_session(session_id, user_id, db)

        result = await db.execute(
            select(ContextSnapshot).where(
                ContextSnapshot.session_id == session_id,
                ContextSnapshot.user_id == user_id,
            )
        )
        snapshot = result.scalar_one_or_none()

        if snapshot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No context snapshot reported yet for this participant",
            )
        return snapshot

    @staticmethod
    async def list_context(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> dict:
        """List all context snapshots in a session (participants only)."""
        await ContextEngineService._load_session(session_id, user_id, db)

        result = await db.execute(
            select(ContextSnapshot)
            .where(ContextSnapshot.session_id == session_id)
            .order_by(ContextSnapshot.updated_at.desc())
        )
        snapshots = result.scalars().all()
        return {
            "session_id": session_id,
            "total_snapshots": len(snapshots),
            "snapshots": snapshots,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _load_session(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> Session:
        """Load a session and verify the user is a participant."""
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

        is_participant = any(p.user_id == user_id for p in session.participants)
        if not is_participant:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a participant of this session",
            )
        return session
