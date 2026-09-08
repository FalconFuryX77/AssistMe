"""Intelligent Assistance (Phase 11).

What this does now
------------------
The inherited implementation counted occurrences of a ``(user, app, action)``
signature, suggested anything seen twice, and reported a "confidence" of
``count / 4``. That is not learning; it is a histogram with a threshold, and it
had three concrete defects, each addressed here:

* **No notion of success.** A count records that an action was *taken*, not that
  it *worked* — so an action a helper retried five times because it kept failing
  outranked one that worked immediately. Exposure and reward are now tracked
  separately and ranked by a Beta-Bernoulli posterior over the success rate.

* **No recency.** A monotone counter means a habit abandoned a year ago
  outranks one formed last week, forever. Evidence now decays exponentially
  with a six-week half-life.

* **No sense of order.** It could only answer "what has this person done
  before?", never "what usually comes next?" — which is the question a helper
  mid-session actually has. Ordering comes from the sequence recommender in
  :mod:`ml.sequence`, backed by an online transition table.

Suggestions are intersected with the safety envelope's admissible set before
they are shown. Suggesting an action and then refusing it is a worse experience
than never suggesting it, and it teaches helpers to expect capabilities they do
not have.
"""

from __future__ import annotations

import hashlib
import json
import logging
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
    DECAY_HALF_LIFE_DAYS,
    AssistanceActionTransition,
    AssistanceSuggestion,
    AssistanceTaskPattern,
    PreferredAssistanceMode,
)
from models.session import Session

logger = logging.getLogger(__name__)

#: Minimum *decayed* evidence before a pattern is offered as a suggestion.
#: Expressed in decayed units rather than raw counts, so two observations a
#: year apart no longer clear the bar the way two last week do.
REPEATED_TASK_THRESHOLD = 1.5

#: Maximum suggestions returned. Three is what the interface shows; returning
#: more would be optimising a metric nobody sees.
MAX_SUGGESTIONS = 3

_ACTION_TITLES: dict[str, str] = {
    "remote_control": "Take control to fix this",
    "screen_share": "Start screen sharing",
    "voice": "Talk them through it",
    "pointer": "Point at what to tap",
    "drawing": "Draw on their screen",
    "chat": "Send a written note",
}


def _decay_factor(last_seen: datetime, now: datetime) -> float:
    """Exponential decay weight for evidence last observed at ``last_seen``.

    ``0.5 ** (Δdays / half_life)``: one half-life halves the weight. Applying it
    to the stored decayed value on each update keeps the running total correct
    with O(1) work per observation, rather than needing the full event history.
    """
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    elapsed_days = max(0.0, (now - last_seen).total_seconds() / 86400.0)
    return 0.5 ** (elapsed_days / DECAY_HALF_LIFE_DAYS)


class IntelligentAssistanceService:
    """Learns from assistance outcomes and produces ranked suggestions."""

    # ------------------------------------------------------------------
    # Learning
    # ------------------------------------------------------------------

    @staticmethod
    async def record_task(
        session_id: str,
        user_id: str,
        request: TaskRecordRequest,
        db: AsyncSession,
    ) -> TaskPatternResponse:
        """Record an observed assistance action and its outcome."""
        await IntelligentAssistanceService._load_session(session_id, user_id, db)

        signature = IntelligentAssistanceService._signature(
            foreground_app=request.foreground_app,
            platform=request.platform,
            action=request.action,
        )
        now = datetime.now(timezone.utc)
        succeeded = bool(getattr(request, "succeeded", True))

        pattern = (
            await db.execute(
                select(AssistanceTaskPattern).where(
                    AssistanceTaskPattern.user_id == user_id,
                    AssistanceTaskPattern.context_signature == signature,
                )
            )
        ).scalar_one_or_none()

        if pattern is None:
            pattern = AssistanceTaskPattern(
                user_id=user_id,
                context_signature=signature,
                foreground_app=request.foreground_app,
                platform=request.platform,
                action=request.action,
                occurrence_count=1,
                success_count=1 if succeeded else 0,
                decayed_count=1.0,
                decayed_success=1.0 if succeeded else 0.0,
                first_occurred_at=now,
                last_occurred_at=now,
            )
            db.add(pattern)
        else:
            # Decay accumulated evidence to "now" before adding this
            # observation, so old and new evidence share a time basis.
            factor = _decay_factor(pattern.last_occurred_at, now)
            pattern.decayed_count = pattern.decayed_count * factor + 1.0
            pattern.decayed_success = pattern.decayed_success * factor + (
                1.0 if succeeded else 0.0
            )
            pattern.occurrence_count += 1
            if succeeded:
                pattern.success_count += 1
            pattern.last_occurred_at = now

        await IntelligentAssistanceService._record_transition(
            user_id, getattr(request, "previous_action", None), request.action, now, db
        )

        await db.commit()
        await db.refresh(pattern)
        return TaskPatternResponse.model_validate(pattern)

    @staticmethod
    async def _record_transition(
        user_id: str,
        previous_action: str | None,
        action: str,
        now: datetime,
        db: AsyncSession,
    ) -> None:
        """Maintain the online first-order transition matrix.

        Updated on every observation so the recommender is useful from a user's
        first session rather than only after the next offline training run —
        which matters because the counts that make a personal model useful
        accumulate a handful at a time.
        """
        previous = previous_action or ""
        transition = (
            await db.execute(
                select(AssistanceActionTransition).where(
                    AssistanceActionTransition.user_id == user_id,
                    AssistanceActionTransition.prev_action == previous,
                    AssistanceActionTransition.next_action == action,
                )
            )
        ).scalar_one_or_none()

        if transition is None:
            db.add(
                AssistanceActionTransition(
                    user_id=user_id,
                    prev_action=previous,
                    next_action=action,
                    transition_count=1,
                    decayed_count=1.0,
                    last_occurred_at=now,
                )
            )
        else:
            factor = _decay_factor(transition.last_occurred_at, now)
            transition.decayed_count = transition.decayed_count * factor + 1.0
            transition.transition_count += 1
            transition.last_occurred_at = now

    @staticmethod
    async def list_task_patterns(user_id: str, db: AsyncSession) -> dict:
        """A user's learned patterns, strongest first by decayed evidence."""
        patterns = list(
            (
                await db.execute(
                    select(AssistanceTaskPattern)
                    .where(AssistanceTaskPattern.user_id == user_id)
                    .order_by(AssistanceTaskPattern.decayed_count.desc())
                )
            )
            .scalars()
            .all()
        )
        return {
            "user_id": user_id,
            "total_patterns": len(patterns),
            "patterns": [TaskPatternResponse.model_validate(p) for p in patterns],
        }

    # ------------------------------------------------------------------
    # Suggestions
    # ------------------------------------------------------------------

    @staticmethod
    async def get_suggestions(
        session_id: str, user_id: str, db: AsyncSession
    ) -> dict:
        """Produce ranked, safety-filtered suggestions for a session.

        Candidates come from three sources, scored on a common scale so they
        can be *ranked against each other* rather than concatenated:

        1. Learned patterns, scored by posterior success rate weighted by how
           much decayed evidence supports them.
        2. The sequence recommender's next-action distribution.
        3. The user's stated preferred mode.

        Everything is then filtered against the admissible set.
        """
        session = await IntelligentAssistanceService._load_session(
            session_id, user_id, db
        )
        context = await IntelligentAssistanceService._helpee_context(session, db)
        now = datetime.now(timezone.utc)

        allowed = IntelligentAssistanceService._admissible_actions(context)
        candidates: dict[str, dict] = {}

        # --- 1. Learned patterns ------------------------------------------
        for pattern in await IntelligentAssistanceService._repeated_patterns(
            user_id, now, db
        ):
            if pattern.action not in allowed:
                continue
            # Weight the posterior by evidence, so a 100%-success pattern seen
            # twice does not outrank an 85%-success pattern seen fifty times.
            evidence_weight = pattern.decayed_count / (pattern.decayed_count + 3.0)
            candidates[pattern.action] = {
                "type": "repeated_task",
                "score": pattern.posterior_success_rate * evidence_weight,
                "title": _ACTION_TITLES.get(
                    pattern.action, f"Repeat: {pattern.action}"
                ),
                "detail": (
                    f"Worked {pattern.success_count} of "
                    f"{pattern.occurrence_count} times with "
                    f"{pattern.foreground_app or 'this app'}."
                ),
            }

        # --- 2. Sequence recommender ---------------------------------------
        last_action = await IntelligentAssistanceService._last_action(user_id, db)
        for recommendation in IntelligentAssistanceService._recommendations(
            user_id, last_action, allowed
        ):
            action = recommendation["action"]
            existing = candidates.get(action)
            # Blend rather than overwrite: agreement between two independent
            # sources is stronger evidence than either alone.
            blended = (
                0.5 * existing["score"] + 0.5 * recommendation["probability"]
                if existing
                else recommendation["probability"]
            )
            candidates[action] = {
                "type": existing["type"] if existing else "next_action",
                "score": blended,
                "title": existing["title"]
                if existing
                else _ACTION_TITLES.get(action, f"Try {action}"),
                "detail": existing["detail"]
                if existing
                else (
                    "Usually comes next after "
                    f"{last_action or 'starting a session'}."
                ),
                "model_version": recommendation.get("model_version"),
            }

        # --- 3. Stated preference -------------------------------------------
        preferred = await IntelligentAssistanceService._get_preferred_mode(user_id, db)
        if preferred is not None and preferred.mode in allowed:
            existing = candidates.get(preferred.mode)
            candidates[preferred.mode] = {
                "type": existing["type"] if existing else "preferred_mode",
                "score": max(existing["score"] if existing else 0.0, 0.55),
                "title": existing["title"]
                if existing
                else f"Continue with {preferred.mode}",
                "detail": existing["detail"]
                if existing
                else "This is the mode you usually prefer.",
            }

        # --- 4. Cold start ---------------------------------------------------
        if not candidates:
            fallback = "voice" if "voice" in allowed else next(iter(sorted(allowed)), "voice")
            candidates[fallback] = {
                "type": "context_help",
                "score": 0.5,
                "title": (
                    f"Help with {context.foreground_app}"
                    if context is not None and context.foreground_app
                    else "Start with voice guidance"
                ),
                "detail": "Nothing learned yet — voice guidance is the safest start.",
            }

        ranked = sorted(candidates.items(), key=lambda kv: -kv[1]["score"])[
            :MAX_SUGGESTIONS
        ]

        responses: list[AssistanceSuggestionResponse] = []
        for rank, (action, payload) in enumerate(ranked, start=1):
            suggestion = AssistanceSuggestion(
                id=str(uuid.uuid4()),
                session_id=session_id,
                user_id=user_id,
                suggestion_type=payload["type"],
                title=payload["title"],
                detail=payload["detail"],
                action=action,
                confidence=float(min(1.0, max(0.0, payload["score"]))),
                rank=rank,
                model_version=payload.get("model_version"),
                created_at=now,
            )
            db.add(suggestion)
            responses.append(
                AssistanceSuggestionResponse(
                    id=suggestion.id,
                    session_id=session_id,
                    suggestion_type=suggestion.suggestion_type,
                    title=suggestion.title,
                    detail=suggestion.detail,
                    confidence=suggestion.confidence,
                    created_at=suggestion.created_at,
                    action=action,
                    rank=rank,
                )
            )

        await db.commit()
        return {
            "session_id": session_id,
            "total_suggestions": len(responses),
            "suggestions": responses,
        }

    @staticmethod
    async def record_suggestion_outcome(
        suggestion_id: str, accepted: bool, db: AsyncSession
    ) -> None:
        """Record whether a suggestion was acted on.

        Closes the feedback loop. Without it, suggestion quality can only ever
        be measured offline against synthetic sequences; with it, Recall@k and
        MRR become computable from production behaviour.
        """
        suggestion = (
            await db.execute(
                select(AssistanceSuggestion).where(
                    AssistanceSuggestion.id == suggestion_id
                )
            )
        ).scalar_one_or_none()
        if suggestion is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found"
            )
        suggestion.accepted = accepted
        suggestion.responded_at = datetime.now(timezone.utc)
        await db.commit()

    # ------------------------------------------------------------------
    # Preferred mode
    # ------------------------------------------------------------------

    @staticmethod
    async def set_preferred_mode(
        user_id: str, mode: str, db: AsyncSession
    ) -> PreferredModeResponse:
        """Set the user's preferred assistance mode."""
        pref = (
            await db.execute(
                select(PreferredAssistanceMode).where(
                    PreferredAssistanceMode.user_id == user_id
                )
            )
        ).scalar_one_or_none()

        if pref is None:
            pref = PreferredAssistanceMode(
                user_id=user_id, mode=mode, source="explicit", confidence=1.0
            )
            db.add(pref)
        else:
            pref.mode = mode
            pref.source = "explicit"
            pref.confidence = 1.0
            pref.updated_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(pref)
        return PreferredModeResponse.model_validate(pref)

    @staticmethod
    async def get_preferred_mode(
        user_id: str, db: AsyncSession
    ) -> PreferredModeResponse | None:
        """Get the user's preferred assistance mode, if set."""
        pref = await IntelligentAssistanceService._get_preferred_mode(user_id, db)
        return PreferredModeResponse.model_validate(pref) if pref else None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _signature(
        foreground_app: str | None, platform: str | None, action: str
    ) -> str:
        raw = json.dumps(
            {
                "app": foreground_app or "unknown",
                "platform": platform or "unknown",
                "action": action,
            },
            sort_keys=True,
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _admissible_actions(context: ContextSnapshot | None) -> set[str]:
        """Actions the safety envelope currently permits.

        Assistance-mode names and suggestion-action names overlap but are not
        identical — ``screen_share`` and ``chat`` are actions with no
        corresponding privilege mode — so modes are mapped to actions and the
        always-safe actions are added.
        """
        from ml.risk.safety import SafetyEnvelope

        if context is None:
            return {"voice", "chat"}

        modes = set(SafetyEnvelope.admissible(context))
        actions: set[str] = {"chat"}
        if "voice" in modes:
            actions.update({"voice", "screen_share"})
        if "pointer" in modes:
            actions.add("pointer")
        if "drawing" in modes:
            actions.add("drawing")
        if "tap" in modes:
            actions.add("remote_control")
        return actions

    @staticmethod
    def _recommendations(
        user_id: str, last_action: str | None, allowed: set[str]
    ) -> list[dict]:
        """Ask the sequence recommender, tolerating its absence.

        Suggestions are a convenience, never a safety control, so an
        unavailable recommender degrades to the other two candidate sources
        rather than failing the request.
        """
        try:
            from ml.inference import get_inference_service

            results = get_inference_service().recommend_actions(
                user_id, last_action, k=MAX_SUGGESTIONS + 2
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Sequence recommender unavailable: %s", exc)
            return []
        return [r for r in results if r["action"] in allowed]

    @staticmethod
    async def _last_action(user_id: str, db: AsyncSession) -> str | None:
        """The user's most recent recorded action, as the chain's state."""
        pattern = (
            await db.execute(
                select(AssistanceTaskPattern)
                .where(AssistanceTaskPattern.user_id == user_id)
                .order_by(AssistanceTaskPattern.last_occurred_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return pattern.action if pattern else None

    @staticmethod
    async def _repeated_patterns(
        user_id: str, now: datetime, db: AsyncSession
    ) -> list[AssistanceTaskPattern]:
        """Patterns with enough *current* evidence to be worth suggesting.

        The stored ``decayed_count`` is decayed to "now" before the threshold is
        applied. Filtering on the stored value alone would let a pattern that
        crossed the bar a year ago stay above it forever — the very staleness
        the decay exists to prevent.
        """
        patterns = list(
            (
                await db.execute(
                    select(AssistanceTaskPattern)
                    .where(AssistanceTaskPattern.user_id == user_id)
                    .order_by(AssistanceTaskPattern.decayed_count.desc())
                )
            )
            .scalars()
            .all()
        )
        return [
            pattern
            for pattern in patterns
            if pattern.decayed_count * _decay_factor(pattern.last_occurred_at, now)
            >= REPEATED_TASK_THRESHOLD
        ]

    @staticmethod
    async def _get_preferred_mode(
        user_id: str, db: AsyncSession
    ) -> PreferredAssistanceMode | None:
        return (
            await db.execute(
                select(PreferredAssistanceMode).where(
                    PreferredAssistanceMode.user_id == user_id
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _helpee_context(
        session: Session, db: AsyncSession
    ) -> ContextSnapshot | None:
        helpee = next((p for p in session.participants if p.role == "helpee"), None)
        target_id = helpee.user_id if helpee else session.creator_id
        return (
            await db.execute(
                select(ContextSnapshot).where(
                    ContextSnapshot.session_id == session.id,
                    ContextSnapshot.user_id == target_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _load_session(
        session_id: str, user_id: str, db: AsyncSession
    ) -> Session:
        session = (
            await db.execute(
                select(Session)
                .where(Session.id == session_id)
                .options(selectinload(Session.participants))
            )
        ).scalar_one_or_none()

        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
            )
        if not any(p.user_id == user_id for p in session.participants):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a participant of this session",
            )
        return session
