"""Adaptive Policy Engine REST API routes (Phase 9)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas.policy_engine import (
    PolicyCapabilityRequest,
    PolicyConsentRequest,
    PolicyEvaluateRequest,
    PolicyStatusResponse,
)
from api.services.policy_engine_service import AdaptivePolicyEngineService
from core.database import get_db
from models.user import User

router = APIRouter(prefix="/sessions/{session_id}/policy", tags=["policy-engine"])


@router.post("/evaluate", response_model=PolicyStatusResponse)
async def evaluate_policy(
    session_id: str,
    payload: PolicyEvaluateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PolicyStatusResponse:
    """Evaluate adaptive policy from live context (risk → capabilities → mode)."""
    return await AdaptivePolicyEngineService.evaluate(
        session_id=session_id,
        current_user_id=current_user.id,
        request=payload,
        db=db,
    )


@router.post("/capabilities", response_model=PolicyStatusResponse)
async def negotiate_capabilities(
    session_id: str,
    payload: PolicyCapabilityRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PolicyStatusResponse:
    """Explicitly negotiate a capability set constrained by context risk."""
    return await AdaptivePolicyEngineService.negotiate_capabilities(
        session_id=session_id,
        current_user_id=current_user.id,
        capabilities=payload.capabilities,
        db=db,
    )


@router.post("/consent", response_model=PolicyStatusResponse)
async def verify_consent(
    session_id: str,
    payload: PolicyConsentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PolicyStatusResponse:
    """Verify helpee consent before granting remote interaction capabilities."""
    return await AdaptivePolicyEngineService.verify_consent(
        session_id=session_id,
        current_user_id=current_user.id,
        request=payload,
        db=db,
    )


@router.get("/status", response_model=PolicyStatusResponse)
async def get_policy_status(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PolicyStatusResponse:
    """Get the current adaptive policy decision for a session."""
    return await AdaptivePolicyEngineService.get_status(
        session_id=session_id,
        current_user_id=current_user.id,
        db=db,
    )
