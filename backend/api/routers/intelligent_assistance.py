"""Intelligent Assistance REST API routes (Phase 11)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas.intelligent_assistance import (
    PreferredModeRequest,
    PreferredModeResponse,
    SuggestionsResponse,
    TaskPatternListResponse,
    TaskPatternResponse,
    TaskRecordRequest,
)
from api.services.intelligent_assistance_service import IntelligentAssistanceService
from core.database import get_db
from models.user import User

router = APIRouter(tags=["intelligent-assistance"])


@router.post(
    "/sessions/{session_id}/assistance/tasks",
    response_model=TaskPatternResponse,
)
async def record_task(
    session_id: str,
    payload: TaskRecordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskPatternResponse:
    """Learn an assistance task occurrence (repeated-task learning)."""
    return await IntelligentAssistanceService.record_task(
        session_id=session_id,
        user_id=current_user.id,
        request=payload,
        db=db,
    )


@router.get(
    "/sessions/{session_id}/assistance/suggestions",
    response_model=SuggestionsResponse,
)
async def get_suggestions(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get context-aware assistance suggestions for the session."""
    return await IntelligentAssistanceService.get_suggestions(
        session_id=session_id,
        user_id=current_user.id,
        db=db,
    )


@router.get(
    "/users/me/assistance/task-patterns",
    response_model=TaskPatternListResponse,
)
async def list_task_patterns(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List the current user's learned task patterns."""
    return await IntelligentAssistanceService.list_task_patterns(
        user_id=current_user.id,
        db=db,
    )


@router.get(
    "/users/me/assistance/preferred-mode",
    response_model=PreferredModeResponse | None,
)
async def get_preferred_mode(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PreferredModeResponse | None:
    """Get the current user's preferred assistance mode."""
    return await IntelligentAssistanceService.get_preferred_mode(
        user_id=current_user.id,
        db=db,
    )


@router.put(
    "/users/me/assistance/preferred-mode",
    response_model=PreferredModeResponse,
)
async def set_preferred_mode(
    payload: PreferredModeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PreferredModeResponse:
    """Set the current user's preferred assistance mode."""
    return await IntelligentAssistanceService.set_preferred_mode(
        user_id=current_user.id,
        mode=payload.mode,
        db=db,
    )