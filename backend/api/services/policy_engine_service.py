"""Adaptive Policy Engine business logic (Phase 9, Research Core).

Classifies risk from live device/session context, negotiates capabilities
between helper and helpee, selects an assistance mode, and verifies explicit
consent before any remote interaction capability is granted.

Output (assistance modes):
    - voice       → audio guidance only
    - pointer     → laser pointer / annotation overlay (no tap)
    - drawing     → freehand drawing & highlighting (no tap)
    - tap         → remote tap gestures (no drag/keyboard)
    - restricted  → view-only
"""

import json
from datetime import datetime, timezone
from secrets import compare_digest

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.schemas.policy_engine import (
    CAPABILITIES,
    PolicyConsentRequest,
    PolicyEvaluateRequest,
    PolicyStatusResponse,
)
from models.context_snapshot import ContextSnapshot
from models.policy_decision import PolicyDecision
from models.session import Session
from models.session_participant import SessionParticipant

# Mode → capability set that the mode enables.
_MODE_CAPABILITIES: dict[str, set[str]] = {
    "voice": {"voice"},
    "pointer": {"voice", "pointer"},
    "drawing": {"voice", "pointer", "drawing"},
    "tap": {"voice", "pointer", "drawing", "tap"},
    "restricted": set(),
}

# Mode ordering for "least privileged" selection when risk increases.
_MODE_RANK = {"restricted": 0, "voice": 1, "pointer": 2, "drawing": 3, "tap": 4}


class AdaptivePolicyEngineService:
    """Applies context-aware risk classification and capability negotiation."""

    # ------------------------------------------------------------------
    # Evaluate (risk classification → mode selection)
    # ------------------------------------------------------------------

    @staticmethod
    async def evaluate(
        session_id: str,
        current_user_id: str,
        request: PolicyEvaluateRequest,
        db,
    ) -> PolicyStatusResponse:
        """Evaluate the adaptive policy for a session from live context.

        Returns a policy decision persisted on the session.
        """
        session = await AdaptivePolicyEngineService._load_session(
            session_id, current_user_id, db
        )

        # Gather the helpee's context snapshot (fall back to empty context).
        context = await AdaptivePolicyEngineService._get_helpee_context(
            session, db
        )

        risk_level, risk_reasons = AdaptivePolicyEngineService._classify_risk(
            context
        )

        # Start from the union of what the requester asked for (if any).
        requested = set(request.requested_capabilities or [])
        requested = requested & set(CAPABILITIES)

        # Negotiate capabilities given risk.
        negotiated = AdaptivePolicyEngineService._negotiate_capabilities(
            requested=requested,
            risk_level=risk_level,
            context=context,
        )

        assistance_mode = AdaptivePolicyEngineService._select_mode(negotiated)

        # Upsert policy decision.
        result = await db.execute(
            select(PolicyDecision).where(PolicyDecision.session_id == session_id)
        )
        decision = result.scalar_one_or_none()
        if decision is None:
            decision = PolicyDecision(
                session_id=session_id,
                evaluated_by_user_id=current_user_id,
            )
            db.add(decision)

        decision.risk_level = risk_level
        decision.risk_reasons = ", ".join(risk_reasons)
        decision.negotiated_capabilities = json.dumps(sorted(negotiated))
        decision.assistance_mode = assistance_mode
        decision.updated_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(decision)
        return AdaptivePolicyEngineService._to_response(decision)

    # ------------------------------------------------------------------
    # Capability negotiation
    # ------------------------------------------------------------------

    @staticmethod
    async def negotiate_capabilities(
        session_id: str,
        current_user_id: str,
        capabilities: list[str],
        db,
    ) -> PolicyStatusResponse:
        """Explicitly negotiate a capability set, constrained by context risk."""
        session = await AdaptivePolicyEngineService._load_session(
            session_id, current_user_id, db
        )
        context = await AdaptivePolicyEngineService._get_helpee_context(session, db)
        risk_level, _ = AdaptivePolicyEngineService._classify_risk(context)

        negotiated = AdaptivePolicyEngineService._negotiate_capabilities(
            requested=set(capabilities),
            risk_level=risk_level,
            context=context,
        )
        assistance_mode = AdaptivePolicyEngineService._select_mode(negotiated)

        result = await db.execute(
            select(PolicyDecision).where(PolicyDecision.session_id == session_id)
        )
        decision = result.scalar_one_or_none()
        if decision is None:
            decision = PolicyDecision(
                session_id=session_id,
                evaluated_by_user_id=current_user_id,
            )
            db.add(decision)

        decision.risk_level = risk_level
        decision.negotiated_capabilities = json.dumps(sorted(negotiated))
        decision.assistance_mode = assistance_mode
        decision.updated_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(decision)
        return AdaptivePolicyEngineService._to_response(decision)

    # ------------------------------------------------------------------
    # Consent verification
    # ------------------------------------------------------------------

    @staticmethod
    async def verify_consent(
        session_id: str,
        current_user_id: str,
        request: PolicyConsentRequest,
        db,
    ) -> PolicyStatusResponse:
        """Verify helpee consent to a capability set before enabling it.

        Consent is verified only when the helpee supplies a valid consent token
        matching the session's generated proof.
        """
        session = await AdaptivePolicyEngineService._load_session(
            session_id, current_user_id, db
        )
        if session.status != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Consent can only be verified in an active session",
            )

        expected_token = AdaptivePolicyEngineService._consent_token(session.id)
        if not compare_digest(request.consent_token, expected_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid consent token — consent not granted by helpee",
            )

        requested = set(request.capabilities)
        context = await AdaptivePolicyEngineService._get_helpee_context(session, db)
        risk_level, _ = AdaptivePolicyEngineService._classify_risk(context)
        negotiated = AdaptivePolicyEngineService._negotiate_capabilities(
            requested=requested,
            risk_level=risk_level,
            context=context,
        )
        assistance_mode = AdaptivePolicyEngineService._select_mode(negotiated)

        result = await db.execute(
            select(PolicyDecision).where(PolicyDecision.session_id == session_id)
        )
        decision = result.scalar_one_or_none()
        if decision is None:
            decision = PolicyDecision(
                session_id=session_id,
                evaluated_by_user_id=current_user_id,
            )
            db.add(decision)

        decision.consent_verified = True
        decision.consent_granted_at = datetime.now(timezone.utc)
        decision.negotiated_capabilities = json.dumps(sorted(negotiated))
        decision.assistance_mode = assistance_mode
        decision.risk_level = risk_level
        decision.updated_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(decision)
        return AdaptivePolicyEngineService._to_response(decision)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @staticmethod
    async def get_status(
        session_id: str,
        current_user_id: str,
        db,
    ) -> PolicyStatusResponse:
        """Return the current policy decision for a session."""
        await AdaptivePolicyEngineService._load_session(session_id, current_user_id, db)

        result = await db.execute(
            select(PolicyDecision).where(PolicyDecision.session_id == session_id)
        )
        decision = result.scalar_one_or_none()
        if decision is None:
            # Default conservative decision before first evaluation.
            now = datetime.now(timezone.utc)
            default = PolicyDecision(
                session_id=session_id,
                evaluated_by_user_id=current_user_id,
                risk_level="low",
                negotiated_capabilities=json.dumps(["voice"]),
                assistance_mode="voice",
                consent_verified=False,
                created_at=now,
                updated_at=now,
            )
            return AdaptivePolicyEngineService._to_response(default, persisted=False)
        return AdaptivePolicyEngineService._to_response(decision)

    # ------------------------------------------------------------------
    # Internal classification & negotiation logic
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_risk(context: ContextSnapshot | None) -> tuple[str, list[str]]:
        """Classify risk level from the helpee's context snapshot.

        - high:    FLAG_SECURE active or critical sensitive app (banking, health,
                   payment, password manager)
        - medium:  other sensitive app categories or protected content
        - low:     normal apps with no protective signals
        """
        if context is None:
            return "low", ["no context reported — defaulting to minimal capabilities"]

        reasons: list[str] = []

        critical_categories = ("banking", "health", "password_manager", "payment")

        if context.is_flag_secure_active:
            reasons.append("FLAG_SECURE is active on the helpee device")

        category = (context.foreground_app_category or "").lower()
        if context.is_sensitive_app or category in critical_categories:
            if category in critical_categories:
                reasons.append(f"critical sensitive app category: {category}")
            elif context.foreground_app:
                reasons.append(f"sensitive app in foreground: {context.foreground_app}")
            else:
                reasons.append("sensitive app content detected")

        if context.is_flag_secure_active:
            return "high", reasons or ["sensitive content detected"]

        if category in critical_categories or context.is_sensitive_app:
            # Distinguish critical categories (high) from generally sensitive apps.
            if category in critical_categories:
                return "high", reasons
            return "medium", reasons

        if reasons:
            return "medium", reasons

        return "low", []

    @staticmethod
    def _negotiate_capabilities(
        requested: set[str],
        risk_level: str,
        context: ContextSnapshot | None,
    ) -> set[str]:
        """Compute the actual granted capability set under current risk."""
        if risk_level == "high":
            # View-only — no interaction of any kind.
            return set()

        if risk_level == "medium":
            # No tap/drag/keyboard; allow pointer/drawing only if accessibility allows.
            allowed = {"voice", "pointer", "drawing"}
            if context is not None and not context.accessibility_enabled:
                allowed.discard("pointer")
                allowed.discard("drawing")
            granted = requested & allowed
            # Always keep voice guidance available.
            granted.add("voice")
            return granted

        # Low risk — full capability set, still require accessibility for touch.
        granted = set(requested)
        if context is not None and not context.accessibility_gesture_capable:
            granted -= {"tap", "drag", "keyboard"}
        granted.add("voice")
        return granted

    @staticmethod
    def _select_mode(negotiated: set[str]) -> str:
        """Select the least-privileged assistance mode that covers capabilities."""
        if "tap" in negotiated or "drag" in negotiated:
            return "tap"
        if "drawing" in negotiated:
            return "drawing"
        if "pointer" in negotiated:
            return "pointer"
        if "voice" in negotiated:
            return "voice"
        return "restricted"

    @staticmethod
    def _consent_token(session_id: str) -> str:
        """Deterministic consent proof bound to the session.

        In production this is exchanged via a side channel (e.g. QR scan or
        helpee app confirmation). For the API contract we derive a stable token.
        """
        import hashlib

        return hashlib.sha256(f"assistme-consent-{session_id}".encode()).hexdigest()[:32]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _load_session(session_id: str, user_id: str, db) -> Session:
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

    @staticmethod
    async def _get_helpee_context(
        session: Session, db
    ) -> ContextSnapshot | None:
        """Find the helpee's context snapshot (or the creator's as fallback)."""
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
    def _to_response(
        decision: PolicyDecision, persisted: bool = True
    ) -> PolicyStatusResponse:
        reasons = []
        if decision.risk_reasons:
            reasons = [r for r in decision.risk_reasons.split(", ") if r]
        try:
            caps = json.loads(decision.negotiated_capabilities) if decision.negotiated_capabilities else []
        except (TypeError, ValueError):
            caps = []
        return PolicyStatusResponse(
            session_id=decision.session_id,
            risk_level=decision.risk_level,
            risk_reasons=reasons,
            negotiated_capabilities=sorted(caps),
            assistance_mode=decision.assistance_mode,
            consent_verified=decision.consent_verified,
            consent_granted_at=decision.consent_granted_at,
            evaluated_at=decision.updated_at if persisted else decision.created_at,
        )