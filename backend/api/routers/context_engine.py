"""Context Engine REST API routes (Phase 8)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas.context_engine import (
    ContextHistoryResponse,
    ContextReportRequest,
    ContextSnapshotResponse,
)
from api.services.context_engine_service import ContextEngineService
from core.database import get_db
from models.user import User

router = APIRouter(prefix="/sessions/{session_id}/context", tags=["context-engine"])


@router.post("/report", response_model=ContextSnapshotResponse)
async def report_context(
    session_id: str,
    payload: ContextReportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Report the helpee's current device & session context."""
    snapshot = await ContextEngineService.report_context(
        session_id=session_id,
        user_id=current_user.id,
        report=payload,
        db=db,
    )
    return snapshot


@router.get("/me", response_model=ContextSnapshotResponse)
async def get_my_context(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get the current user's context snapshot."""
    return await ContextEngineService.get_context(
        session_id=session_id,
        user_id=current_user.id,
        db=db,
    )


@router.get("/", response_model=ContextHistoryResponse)
async def list_session_context(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List all context snapshots for a session."""
    return await ContextEngineService.list_context(
        session_id=session_id,
        user_id=current_user.id,
        db=db,
    )
