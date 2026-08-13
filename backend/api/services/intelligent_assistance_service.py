"""Intelligent Assistance business logic (Phase 11).

- Learns repeated task patterns (context signature → action, occurrence count).
- Produces context-aware assistance suggestions from learned patterns and the
  current session context.
- Remembers each user's preferred assistance mode.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.schemas.intelligent_assistance import (
    AssistanceSuggestionResponse,
    PreferredModeResponse,
    TaskPatternResponse,
    TaskRecordRequest,
)
from models.context_snapshot import ContextSnapshot
from models.intelligent_assistance import (
    AssistanceSuggestion,
    AssistanceTaskPattern,
    PreferredAssistanceMode,
)
from models.session import Session
from models.session_participant import SessionParticipant

# Minimum occurrences before a task is considered "repeated" and suggested.
REPEATED_TASK_THRESHOLD = 2

# Action → human-readable suggestion template.
_ACTION_TITLES: dict[str, str] = {
    "remote_control": "Remote control helps with this app",
    "screen_share": "Start screen sharing for this app",
    "voice": "Use voice guidance for this app",
    "pointer": "Annotate over this app",
    "drawing": "Draw over this app",
    "chat": "Send a chat message about this app",
}


class IntelligentAssistanceService:
    """Learns repeated tasks and produces context-aware assistance help."""

    # ------------------------------------------------------------------
    # Task pattern learning
    # ------------------------------------------------------------------

    @staticmethod
    async def record_task(
        session_id: str,
        user_id: str,
        request: TaskRecordRequest,
        db: AsyncSession,
    ) -> TaskPatternResponse:
        """Learn/update a task pattern from an observed assistance action.

        The pattern is keyed by a stable signature of (foreground_app, platform,
        action). Occurrence count increments on repeat so the engine can detect
        "repeated tasks" worth suggesting.
        """
        await IntelligentAssistanceService._load_session(session_id, user_id, db)

        signature = IntelligentAssistanceService._signature(
            foreground_app=request.foreground_app,
            platform=request.platform,
            action=request.action,
        )

        result = await db.execute(
            select(AssistanceTaskPattern).where(
                AssistanceTaskPattern.user_id == user_id,
                AssistanceTaskPattern.context_signature == signature,
            )
        )
        pattern = result.scalar_one_or_none()

        if pattern is None:
            pattern = AssistanceTaskPattern(
                user_id=user_id,
                context_signature=signature,
                foreground_app=request.foreground_app,
                platform=request.platform,
                action=request.action,
                occurrence_count=1,
                last_occurred_at=datetime.now(timezone.utc),
            )
            db.add(pattern)
        else:
            pattern.occurrence_count += 1
            pattern.last_occurred_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(pattern)
        return TaskPatternResponse.model_validate(pattern)

    @staticmethod
    async def list_task_patterns(
        user_id: str,
        db: AsyncSession,
    ) -> dict:
        """List a user's learned task patterns, most frequent first."""
        result = await db.execute(
            select(AssistanceTaskPattern)
            .where(AssistanceTaskPattern.user_id == user_id)
            .order_by(AssistanceTaskPattern.occurrence_count.desc())
        )
        patterns = result.scalars().all()
        return {
            "user_id": user_id,
            "total_patterns": len(patterns),
            "patterns": [TaskPatternResponse.model_validate(p) for p in patterns],
        }

    # ------------------------------------------------------------------
    # Context-aware suggestions
    # ------------------------------------------------------------------

    @staticmethod
    async def get_suggestions(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> dict:
        """Produce context-aware assistance suggestions for the session.

        Sources:
            - Repeated task patterns for the current user + helpee context
            - Preferred assistance mode (reminder)
        """
        session = await IntelligentAssistanceService._load_session(session_id, user_id, db)

        # Gather helpee context to ground suggestions in the current app.
        context = await IntelligentAssistanceService._helpee_context(session, db)

        suggestions: list[AssistanceSuggestionResponse] = []
        now = datetime.now(timezone.utc)
        suggestion_id = lambda: str(uuid.uuid4())  # noqa: E731

        # 1) Repeated task patterns.
        patterns = await IntelligentAssistanceService._repeated_patterns(user_id, db)
        for pattern in patterns:
            title = _ACTION_TITLES.get(pattern.action, f"Repeat: {pattern.action}")
            suggestion = AssistanceSuggestion(
                id=suggestion_id(),
                session_id=session_id,
                user_id=user_id,
                suggestion_type="repeated_task",
                title=title,
                detail=(
                    f"You've used {pattern.action} {pattern.occurrence_count} times "
                    f"with {pattern.foreground_app or 'this app'}. Repeat it?"
                ),
                confidence=min(1.0, pattern.occurrence_count / (REPEATED_TASK_THRESHOLD + 2)),
                created_at=now,
            )
            db.add(suggestion)
            suggestions.append(
                AssistanceSuggestionResponse(
                    id=suggestion.id,
                    session_id=session_id,
                    suggestion_type=suggestion.suggestion_type,
                    title=suggestion.title,
                    detail=suggestion.detail,
                    confidence=suggestion.confidence,
                    created_at=suggestion.created_at,
                )
            )

        # 2) Preferred-mode memory.
        preferred = await IntelligentAssistanceService._get_preferred_mode(user_id, db)
        if preferred is not None and not suggestions:
            suggestion = AssistanceSuggestion(
                id=suggestion_id(),
                session_id=session_id,
                user_id=user_id,
                suggestion_type="preferred_mode",
                title=f"Continue with {preferred.mode} mode",
                detail="This is your preferred assistance mode from past sessions.",
                confidence=0.9,
                created_at=now,
            )
            db.add(suggestion)
            suggestions.append(
                AssistanceSuggestionResponse(
                    id=suggestion.id,
                    session_id=session_id,
                    suggestion_type=suggestion.suggestion_type,
                    title=suggestion.title,
                    detail=suggestion.detail,
                    confidence=suggestion.confidence,
                    created_at=suggestion.created_at,
                )
            )

        # 3) Generic context help when nothing learned yet.
        if not suggestions:
            title = "Need help? Start with voice guidance"
            detail = None
            if context is not None and context.foreground_app:
                title = f"Help with {context.foreground_app}"
                detail = "No repeated task found yet — begin with voice guidance."
            suggestion = AssistanceSuggestion(
                id=suggestion_id(),
                session_id=session_id,
                user_id=user_id,
                suggestion_type="context_help",
                title=title,
                detail=detail,
                confidence=0.5,
                created_at=now,
            )
            db.add(suggestion)
            suggestions.append(
                AssistanceSuggestionResponse(
                    id=suggestion.id,
                    session_id=session_id,
                    suggestion_type=suggestion.suggestion_type,
                    title=suggestion.title,
                    detail=suggestion.detail,
                    confidence=suggestion.confidence,
                    created_at=suggestion.created_at,
                )
            )

        await db.commit()
        return {
            "session_id": session_id,
            "total_suggestions": len(suggestions),
            "suggestions": suggestions,
        }

    # ------------------------------------------------------------------
    # Preferred mode memory
    # ------------------------------------------------------------------

    @staticmethod
    async def set_preferred_mode(
        user_id: str,
        mode: str,
        db: AsyncSession,
    ) -> PreferredModeResponse:
        """Set (or create) the user's preferred assistance mode."""
        result = await db.execute(
            select(PreferredAssistanceMode).where(
                PreferredAssistanceMode.user_id == user_id
            )
        )
        pref = result.scalar_one_or_none()
        if pref is None:
            pref = PreferredAssistanceMode(user_id=user_id, mode=mode)
            db.add(pref)
        else:
            pref.mode = mode
            pref.updated_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(pref)
        return PreferredModeResponse.model_validate(pref)

    @staticmethod
    async def get_preferred_mode(
        user_id: str,
        db: AsyncSession,
    ) -> PreferredModeResponse | None:
        """Get the user's preferred assistance mode, if set."""
        return await IntelligentAssistanceService._get_preferred_mode(user_id, db)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _signature(foreground_app: str | None, platform: str | None, action: str) -> str:
        raw = json.dumps(
            {"app": foreground_app or "unknown", "platform": platform or "unknown", "action": action},
            sort_keys=True,
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    async def _repeated_patterns(
        user_id: str, db: AsyncSession
    ) -> list[AssistanceTaskPattern]:
        result = await db.execute(
            select(AssistanceTaskPattern)
            .where(
                AssistanceTaskPattern.user_id == user_id,
                AssistanceTaskPattern.occurrence_count >= REPEATED_TASK_THRESHOLD,
            )
            .order_by(AssistanceTaskPattern.occurrence_count.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def _get_preferred_mode(
        user_id: str, db: AsyncSession
    ) -> PreferredAssistanceMode | None:
        result = await db.execute(
            select(PreferredAssistanceMode).where(
                PreferredAssistanceMode.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _helpee_context(session: Session, db: AsyncSession) -> ContextSnapshot | None:
        helpee = next(
            (p for p in session.participants if p.role == "helpee"), None
        )
        target_id = helpee.user_id if helpee else session.creator_id
        result = await db.execute(
            select(ContextSnapshot).where(
                ContextSnapshot.session_id == session.id,
                ContextSnapshot.user_id == target_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _load_session(session_id: str, user_id: str, db: AsyncSession) -> Session:
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