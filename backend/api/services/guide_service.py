"""Guide service for generating and managing step-by-step visual session guides."""

import logging
import os
import uuid
from typing import Any
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models.guide import GuideStep, SessionGuide
from models.session import Session
from models.session_participant import SessionParticipant

logger = logging.getLogger(__name__)


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

    @staticmethod
    def filter_candidate_keyframes(keyframes: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        """Filter out duplicate, rapid-fire, or redundant keyframes.
        
        Ensures only meaningful, settled states are sent for AI step synthesis.
        """
        if not keyframes:
            return []

        filtered: list[dict[str, Any]] = []
        last_hash: int | None = None

        for kf in keyframes:
            img = kf.get("image_url") or ""
            # Simple content hash to prevent consecutive duplicate frames
            current_hash = hash(img[:256] + img[-256:]) if len(img) > 512 else hash(img)
            if last_hash is not None and current_hash == last_hash:
                continue

            last_hash = current_hash
            filtered.append(kf)
            if len(filtered) >= 6:  # Cap at top 6 distinct candidates
                break

        return filtered

    @staticmethod
    async def _call_mimo_synthesis(
        title_hint: str | None,
        transcript_text: str | None,
        keyframes: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Call MiMo-V2.5 / OpenAI-compatible omnimodal model for visual guide extraction."""
        import httpx
        import json

        api_key = settings.AI_API_KEY
        if not api_key:
            logger.info("AI_API_KEY not set; using local semantic synthesis fallback")
            return None

        prompt = (
            "You are an empathetic, expert assistive AI helper for elderly and non-technical users. "
            "Analyze these assistance session screenshots and transcript. "
            "Filter out any accidental test scribbles or non-informative frames. "
            "Select the 2 to 5 essential steps that teach the user how to solve their problem. "
            "Return valid JSON strictly adhering to this format:\n"
            "{\n"
            '  "title": "Clear, friendly title (e.g., How to Change Language to English)",\n'
            '  "summary": "1-2 sentence friendly explanation of what was fixed/learned.",\n'
            '  "category": "settings | wifi | display | general",\n'
            '  "steps": [\n'
            '    {\n'
            '      "step_number": 1,\n'
            '      "title": "Short step title (e.g., Open Settings)",\n'
            '      "instruction": "Simple, large-print instruction on what to tap.",\n'
            '      "keyframe_index": 0\n'
            '    }\n'
            "  ]\n"
            "}"
        )

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if transcript_text:
            content.append({"type": "text", "text": f"Session Transcript:\n{transcript_text}"})
        if title_hint:
            content.append({"type": "text", "text": f"Session Topic Hint: {title_hint}"})

        for idx, kf in enumerate(keyframes):
            img_url = kf.get("image_url")
            if img_url and (img_url.startswith("http") or img_url.startswith("data:")):
                content.append({
                    "type": "image_url",
                    "image_url": {"url": img_url},
                })
                content.append({"type": "text", "text": f"[Candidate Screenshot #{idx}]"})

        payload = {
            "model": settings.AI_MODEL,
            "messages": [
                {"role": "system", "content": "You output strictly valid JSON with no markdown wrapping."},
                {"role": "user", "content": content},
            ],
            "temperature": 0.2,
            "max_tokens": 1024,
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            url = f"{settings.AI_BASE_URL.rstrip('/')}/chat/completions"
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    msg = data["choices"][0]["message"]["content"].strip()
                    if msg.startswith("```"):
                        msg = msg.split("```")[1]
                        if msg.startswith("json"):
                            msg = msg[4:]
                    return json.loads(msg.strip())
                else:
                    logger.warning(f"MiMo API returned status {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.warning(f"MiMo omnimodal synthesis failed, falling back to heuristic: {e}")

        return None

    @staticmethod
    async def synthesize_guide_from_session(
        db: AsyncSession,
        session_id: str,
        user_id: str,
        transcript_text: str | None = None,
        keyframes: list[dict[str, Any]] | None = None,
        custom_title: str | None = None,
    ) -> SessionGuide:
        """Synthesize a structured visual guide from session context and keyframes.
        
        Filters candidate frames, applies MiMo omnimodal inference if configured,
        and falls back gracefully to semantic structure.
        """
        # Determine helper
        helper_id = None
        stmt = select(SessionParticipant).where(SessionParticipant.session_id == str(session_id))
        res = await db.execute(stmt)
        participants = list(res.scalars().all())
        for p in participants:
            if p.user_id != str(user_id):
                helper_id = p.user_id
                break

        # Filter noise and redundant keyframes
        filtered_kf = GuideService.filter_candidate_keyframes(keyframes)

        # Attempt MiMo Omnimodal Synthesis
        mimo_result = await GuideService._call_mimo_synthesis(
            title_hint=custom_title,
            transcript_text=transcript_text,
            keyframes=filtered_kf,
        )

        if mimo_result and "steps" in mimo_result and isinstance(mimo_result["steps"], list):
            title = mimo_result.get("title") or custom_title or "Help Guide"
            summary = mimo_result.get("summary") or "Visual guide captured during your help session."
            category = mimo_result.get("category") or "general"
            steps_data: list[dict[str, Any]] = []

            for idx, s in enumerate(mimo_result["steps"], start=1):
                kf_idx = s.get("keyframe_index")
                img = filtered_kf[kf_idx].get("image_url") if (isinstance(kf_idx, int) and 0 <= kf_idx < len(filtered_kf)) else None
                steps_data.append({
                    "step_number": idx,
                    "title": s.get("title", f"Step {idx}"),
                    "instruction": s.get("instruction", ""),
                    "image_url": img,
                })
        else:
            # Fallback heuristic synthesis
            title = custom_title or "Assistance Session Summary"
            summary = "Step-by-step visual walkthrough captured during your help session."
            category = "general"
            steps_data = []

            if filtered_kf:
                for idx, kf in enumerate(filtered_kf, start=1):
                    step_title = kf.get("title", f"Step {idx}")
                    instruction = kf.get("instruction", "Follow the highlighted step on screen.")
                    image_url = kf.get("image_url")
                    steps_data.append({
                        "step_number": idx,
                        "title": step_title,
                        "instruction": instruction,
                        "image_url": image_url,
                    })
            elif transcript_text:
                lines = [line.strip() for line in transcript_text.split("\n") if line.strip()]
                for idx, line in enumerate(lines[:5], start=1):
                    steps_data.append({
                        "step_number": idx,
                        "title": f"Step {idx}",
                        "instruction": line,
                        "image_url": None,
                    })
            else:
                steps_data.append({
                    "step_number": 1,
                    "title": "Review",
                    "instruction": "Open the application and proceed as guided during the call.",
                    "image_url": None,
                })

        return await GuideService.create_guide(
            db=db,
            user_id=user_id,
            session_id=session_id,
            helper_id=helper_id,
            title=title,
            summary=summary,
            category=category,
            steps_data=steps_data,
        )
