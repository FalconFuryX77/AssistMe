"""Adaptive Policy Engine (Phase 9, research core).

What this does now
------------------
The inherited implementation classified risk with a chain of ``if`` statements
and returned one of three strings. It is replaced by a three-layer decision:

1. **Model layer** — a calibrated risk classifier and a contextual bandit
   propose a risk level and an assistance mode
   (:mod:`ml.inference`).
2. **Safety envelope** — a deterministic rule ceiling clamps the proposal
   (:mod:`ml.risk.safety`). The clamp only ever lowers privilege.
3. **Database constraints** — ``ck_policy_decisions_high_risk_limits_mode``
   refuses to store an elevated mode at high risk, whatever layers one and two
   concluded.

The rule engine remains the fallback for every failure and every abstention, so
the system's floor is exactly its previous behaviour. That is the property that
makes shipping a model on this path defensible: the worst case is the old
system, not an unpredictable one.

Every model-influenced decision is written to ``ml_decision_log`` with the
feature vector, the propensity and the latency, which is what makes off-policy
evaluation of a future policy possible without experimenting on users.
"""

from __future__ import annotations

import logging
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
from api.services.audit_ledger_service import AuditLedgerService
from core.config import settings
from core.db.enums import MODE_CAPABILITIES, RISK_RANK
from models.context_snapshot import ContextSnapshot
from models.ml_decision_log import MLDecisionLog
from models.policy_decision import PolicyDecision
from models.session import Session

logger = logging.getLogger(__name__)


class AdaptivePolicyEngineService:
    """Context-aware risk classification, capability negotiation, and consent."""

    # ------------------------------------------------------------------
    # Evaluate
    # ------------------------------------------------------------------

    @staticmethod
    async def evaluate(
        session_id: str,
        current_user_id: str,
        request: PolicyEvaluateRequest,
        db: AsyncSession,
    ) -> PolicyStatusResponse:
        """Evaluate the adaptive policy for a session from live context."""
        session = await AdaptivePolicyEngineService._load_session(
            session_id, current_user_id, db
        )
        context = await AdaptivePolicyEngineService._get_helpee_context(session, db)

        requested = set(request.requested_capabilities or []) & set(CAPABILITIES)

        decision = await AdaptivePolicyEngineService._decide(
            context=context,
            requested_capabilities=requested or None,
            db=db,
        )

        record = await AdaptivePolicyEngineService._persist(
            session_id=session_id,
            user_id=current_user_id,
            decision=decision,
            db=db,
        )

        await AuditLedgerService.append(
            db,
            session_id=session_id,
            actor_user_id=current_user_id,
            event_type="policy_evaluated",
            event_category="capability",
            detail={
                "risk_level": decision.risk_level,
                "assistance_mode": decision.assistance_mode,
                "decision_source": decision.decision_source,
                "model_version": decision.model_version,
                "envelope_clamped": decision.envelope_clamped,
            },
        )

        await db.commit()
        await db.refresh(record)
        return AdaptivePolicyEngineService._to_response(
            record, capability_names=decision.capabilities
        )

    # ------------------------------------------------------------------
    # Negotiate
    # ------------------------------------------------------------------

    @staticmethod
    async def negotiate_capabilities(
        session_id: str,
        current_user_id: str,
        capabilities: list[str],
        db: AsyncSession,
    ) -> PolicyStatusResponse:
        """Negotiate an explicit capability set, constrained by context risk."""
        session = await AdaptivePolicyEngineService._load_session(
            session_id, current_user_id, db
        )
        context = await AdaptivePolicyEngineService._get_helpee_context(session, db)

        decision = await AdaptivePolicyEngineService._decide(
            context=context,
            requested_capabilities=set(capabilities) & set(CAPABILITIES),
            db=db,
        )
        record = await AdaptivePolicyEngineService._persist(
            session_id=session_id,
            user_id=current_user_id,
            decision=decision,
            db=db,
        )
        await db.commit()
        await db.refresh(record)
        return AdaptivePolicyEngineService._to_response(
            record, capability_names=decision.capabilities
        )

    # ------------------------------------------------------------------
    # Consent
    # ------------------------------------------------------------------

    @staticmethod
    async def verify_consent(
        session_id: str,
        current_user_id: str,
        request: PolicyConsentRequest,
        db: AsyncSession,
    ) -> PolicyStatusResponse:
        """Verify helpee consent before a capability set is enabled.

        Consent is checked *before* the policy is recomputed, and the granted
        set is the intersection of what was consented to with what the policy
        allows. Consent can never widen the policy: agreeing to remote control
        inside a banking app does not make it available, because the envelope
        still forbids it. Consent is necessary, not sufficient.
        """
        session = await AdaptivePolicyEngineService._load_session(
            session_id, current_user_id, db
        )
        if session.status != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Consent can only be verified in an active session",
            )

        expected = AdaptivePolicyEngineService._consent_token(session.id)
        if not compare_digest(request.consent_token, expected):
            await AuditLedgerService.append(
                db,
                session_id=session_id,
                actor_user_id=current_user_id,
                event_type="consent_token_rejected",
                event_category="security",
                detail={"capabilities": sorted(set(request.capabilities))},
                commit=True,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid consent token — consent not granted by helpee",
            )

        context = await AdaptivePolicyEngineService._get_helpee_context(session, db)
        decision = await AdaptivePolicyEngineService._decide(
            context=context,
            requested_capabilities=set(request.capabilities) & set(CAPABILITIES),
            db=db,
        )

        record = await AdaptivePolicyEngineService._persist(
            session_id=session_id,
            user_id=current_user_id,
            decision=decision,
            db=db,
            consent_verified=True,
        )

        await AuditLedgerService.append(
            db,
            session_id=session_id,
            actor_user_id=current_user_id,
            event_type="consent_verified",
            event_category="consent",
            detail={
                "granted_capabilities": sorted(decision.capabilities),
                "assistance_mode": decision.assistance_mode,
                "risk_level": decision.risk_level,
            },
        )

        await db.commit()
        await db.refresh(record)
        return AdaptivePolicyEngineService._to_response(
            record, capability_names=decision.capabilities
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @staticmethod
    async def get_status(
        session_id: str, current_user_id: str, db: AsyncSession
    ) -> PolicyStatusResponse:
        """Return the current policy decision, or a conservative default."""
        await AdaptivePolicyEngineService._load_session(session_id, current_user_id, db)

        record = (
            await db.execute(
                select(PolicyDecision)
                .where(PolicyDecision.session_id == session_id)
                .options(selectinload(PolicyDecision.capabilities))
            )
        ).scalar_one_or_none()

        if record is None:
            now = datetime.now(timezone.utc)
            default = PolicyDecision(
                session_id=session_id,
                evaluated_by_user_id=current_user_id,
                risk_level="low",
                assistance_mode="voice",
                decision_source="rules",
                consent_verified=False,
                created_at=now,
                updated_at=now,
            )
            default.capabilities = []
            return AdaptivePolicyEngineService._to_response(
                default, persisted=False, capability_names={"voice"}
            )
        return AdaptivePolicyEngineService._to_response(record)

    # ------------------------------------------------------------------
    # Decision core
    # ------------------------------------------------------------------

    @staticmethod
    async def _decide(
        context: ContextSnapshot | None,
        requested_capabilities: set[str] | None,
        db: AsyncSession,
    ):
        """Produce a decision and log it if a model was involved."""
        from ml.inference import get_inference_service

        app_profile = await AdaptivePolicyEngineService._app_profile(context, db)

        decision = get_inference_service().decide(
            context,
            app_profile=app_profile,
            requested_capabilities=requested_capabilities,
        )

        if settings.ML_LOG_DECISIONS and decision.decision_source == "model":
            db.add(
                MLDecisionLog(
                    session_id=getattr(context, "session_id", None),
                    user_id=getattr(context, "user_id", None),
                    decision_kind="mode_selection",
                    model_version=decision.model_version or "unknown",
                    features=decision.features,
                    action=decision.assistance_mode,
                    candidate_actions=decision.candidate_actions,
                    propensity=decision.propensity,
                    confidence=decision.model_confidence,
                    envelope_clamped=decision.envelope_clamped,
                    latency_us=decision.latency_us,
                )
            )

        return decision

    @staticmethod
    async def _app_profile(context: ContextSnapshot | None, db: AsyncSession):
        """Read population risk statistics for the foreground app.

        Sourced from ``mv_app_risk_profile``, which is where the database's
        materialised views feed the model directly. A missing view or an app
        below the view's k>=5 aggregation floor yields ``None``, which the
        feature extractor handles as the cold-start case.
        """
        if context is None or not getattr(context, "foreground_app", None):
            return None

        from sqlalchemy import text

        from core.db.dialect import is_postgres

        if not is_postgres(db.bind):
            return None

        try:
            row = (
                await db.execute(
                    text(
                        "SELECT high_risk_rate, sensitive_rate, observation_count "
                        "FROM mv_app_risk_profile WHERE foreground_app = :app"
                    ),
                    {"app": context.foreground_app},
                )
            ).first()
        except Exception as exc:  # noqa: BLE001 - the view may not exist yet
            logger.debug("App risk profile unavailable: %s", exc)
            return None

        if row is None:
            return None
        return {
            "high_risk_rate": row[0] or 0.0,
            "sensitive_rate": row[1] or 0.0,
            "observation_count": row[2] or 0.0,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @staticmethod
    async def _persist(
        session_id: str,
        user_id: str,
        decision,
        db: AsyncSession,
        *,
        consent_verified: bool | None = None,
    ) -> PolicyDecision:
        """Upsert the session's policy decision."""
        record = (
            await db.execute(
                select(PolicyDecision)
                .where(PolicyDecision.session_id == session_id)
                .options(selectinload(PolicyDecision.capabilities))
            )
        ).scalar_one_or_none()

        now = datetime.now(timezone.utc)
        if record is None:
            record = PolicyDecision(
                session_id=session_id,
                evaluated_by_user_id=user_id,
                created_at=now,
                updated_at=now,
            )
            record.capabilities = []
            db.add(record)
        else:
            record.updated_at = max(now, record.created_at)

        record.risk_level = decision.risk_level
        record.risk_reasons = list(decision.reasons) or None
        record.risk_score = decision.risk_score
        record.assistance_mode = decision.assistance_mode
        record.decision_source = decision.decision_source
        record.model_version = decision.model_version
        record.model_confidence = decision.model_confidence
        record.envelope_clamped = decision.envelope_clamped
        record.set_capabilities(decision.capabilities)

        if consent_verified:
            record.consent_verified = True
            record.consent_granted_at = datetime.now(timezone.utc)

        await db.flush()
        return record

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _consent_token(session_id: str) -> str:
        """Deterministic consent proof bound to the session.

        In production this is exchanged over a side channel (the helpee's own
        confirmation in the app). Derived here so the API contract is testable.
        """
        from hashlib import sha256

        return sha256(f"assistme-consent-{session_id}".encode()).hexdigest()[:32]

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

    @staticmethod
    async def _get_helpee_context(
        session: Session, db: AsyncSession
    ) -> ContextSnapshot | None:
        """The helpee's context — the device whose screen is at stake."""
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
    def _to_response(
        decision: PolicyDecision,
        persisted: bool = True,
        capability_names: set[str] | None = None,
    ) -> PolicyStatusResponse:
        if capability_names is None:
            try:
                capability_names = decision.capability_set
            except Exception:  # noqa: BLE001 - unloaded relationship on a transient row
                capability_names = set(
                    MODE_CAPABILITIES.get(decision.assistance_mode, frozenset())
                )

        return PolicyStatusResponse(
            session_id=decision.session_id,
            risk_level=decision.risk_level,
            risk_reasons=list(decision.risk_reasons or []),
            negotiated_capabilities=sorted(capability_names),
            assistance_mode=decision.assistance_mode,
            consent_verified=decision.consent_verified,
            consent_granted_at=decision.consent_granted_at,
            evaluated_at=decision.updated_at if persisted else decision.created_at,
            decision_source=getattr(decision, "decision_source", "rules"),
            model_version=getattr(decision, "model_version", None),
            risk_score=getattr(decision, "risk_score", None),
            model_confidence=getattr(decision, "model_confidence", None),
            envelope_clamped=bool(getattr(decision, "envelope_clamped", False)),
        )
