"""Session Guides API routes."""

import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas.guide import (
    GuideGenerateRequest,
    GuideResponse,
    GuideStepResponse,
)
from api.services.guide_service import GuideService
from core.database import get_db
from models.user import User

router = APIRouter(tags=["guides"])


class SessionGuideSynthesizePayload(BaseModel):
    """Payload to trigger post-session guide synthesis."""

    title: str | None = None
    transcript_text: str | None = None
    keyframes: list[dict[str, Any]] | None = None


def _format_guide(guide) -> dict[str, Any]:
    return {
        "id": str(guide.id),
        "session_id": str(guide.session_id) if guide.session_id else None,
        "user_id": str(guide.user_id),
        "helper_id": str(guide.helper_id) if guide.helper_id else None,
        "title": guide.title,
        "summary": guide.summary,
        "category": guide.category,
        "steps_count": guide.steps_count,
        "created_at": guide.created_at,
        "updated_at": guide.updated_at,
        "steps": [
            {
                "id": str(s.id),
                "step_number": s.step_number,
                "title": s.title,
                "instruction": s.instruction,
                "image_url": s.image_url,
                "created_at": s.created_at,
            }
            for s in (guide.steps or [])
        ],
    }


@router.get("/guides", response_model=list[GuideResponse])
async def list_guides(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all guides available to the authenticated user."""
    guides = await GuideService.get_user_guides(db=db, user_id=str(current_user.id))
    return [_format_guide(g) for g in guides]


@router.get("/guides/{guide_id}", response_model=GuideResponse)
async def get_guide(
    guide_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve a specific session guide with its step walkthrough."""
    guide = await GuideService.get_guide_by_id(db=db, guide_id=guide_id, user_id=str(current_user.id))
    return _format_guide(guide)


@router.post("/guides", response_model=GuideResponse, status_code=status.HTTP_201_CREATED)
async def create_guide(
    payload: GuideGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Manually create or save a step-by-step guide."""
    steps_data = [step.model_dump() for step in payload.steps]
    guide = await GuideService.create_guide(
        db=db,
        user_id=str(current_user.id),
        title=payload.title,
        summary=payload.summary,
        category=payload.category,
        session_id=payload.session_id,
        steps_data=steps_data,
    )
    return _format_guide(guide)


@router.post("/sessions/{session_id}/guide/generate", response_model=GuideResponse, status_code=status.HTTP_201_CREATED)
async def synthesize_guide(
    session_id: str,
    payload: SessionGuideSynthesizePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Synthesize a structured guide after an assistance session."""
    guide = await GuideService.synthesize_guide_from_session(
        db=db,
        session_id=session_id,
        user_id=str(current_user.id),
        transcript_text=payload.transcript_text,
        keyframes=payload.keyframes,
        custom_title=payload.title,
    )
    return _format_guide(guide)


@router.delete("/guides/{guide_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_guide(
    guide_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a guide owned by the user."""
    await GuideService.delete_guide(db=db, guide_id=guide_id, user_id=str(current_user.id))
