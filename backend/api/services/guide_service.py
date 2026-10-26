"""Guide service for generating and managing step-by-step visual session guides."""

import uuid
from typing import Any
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.guide import GuideStep, SessionGuide


class GuideService:
    """Business logic for session how-to guides."""

    @staticmethod
    async def create_guide(
        db: AsyncSession,
        user_id: str,
        title: str,
        summary: str = "",
        category: str = "general",
        session_id: str | None = None,
        helper_id: str | None = None,
        steps_data: list[dict[str, Any]] | None = None,
    ) -> SessionGuide:
        """Create a new guide with its sequential steps."""
        guide = SessionGuide(
            id=str(uuid.uuid4()),
            user_id=str(user_id),
            session_id=str(session_id) if session_id else None,
            helper_id=str(helper_id) if helper_id else None,
            title=title,
            summary=summary,
            category=category,
            steps_count=len(steps_data) if steps_data else 0,
        )
        db.add(guide)
        await db.flush()

        if steps_data:
            for idx, step_dict in enumerate(steps_data, start=1):
                step = GuideStep(
                    id=str(uuid.uuid4()),
                    guide_id=guide.id,
                    step_number=step_dict.get("step_number", idx),
                    title=step_dict.get("title", f"Step {idx}"),
                    instruction=step_dict.get("instruction", ""),
                    image_url=step_dict.get("image_url"),
                )
                db.add(step)

        await db.commit()
        await db.refresh(guide)
        return guide

    @staticmethod
    async def get_user_guides(
        db: AsyncSession,
        user_id: str,
    ) -> list[SessionGuide]:
        """Fetch all guides where the user is either the helpee or helper."""
        stmt = (
            select(SessionGuide)
            .where((SessionGuide.user_id == str(user_id)) | (SessionGuide.helper_id == str(user_id)))
            .order_by(SessionGuide.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_guide_by_id(
        db: AsyncSession,
        guide_id: str,
        user_id: str,
    ) -> SessionGuide:
        """Fetch a specific guide by ID, ensuring user access."""
        stmt = select(SessionGuide).where(SessionGuide.id == str(guide_id))
        result = await db.execute(stmt)
        guide = result.scalar_one_or_none()

        if guide is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Guide not found",
            )

        if guide.user_id != str(user_id) and guide.helper_id != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this guide",
            )

        return guide

    @staticmethod
    async def delete_guide(
        db: AsyncSession,
        guide_id: str,
        user_id: str,
    ) -> bool:
        """Delete a guide owned by the user."""
        guide = await GuideService.get_guide_by_id(db, guide_id, user_id)
        await db.delete(guide)
        await db.commit()
        return True
