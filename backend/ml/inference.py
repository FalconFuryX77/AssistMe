"""Runtime inference: the only entry point the API uses to reach a model.

Operating principles
--------------------
This module sits on the hot path of a live assistance session, where an elderly
person is waiting and a helper is looking at a blank screen. Four rules follow
from that, and they are enforced here rather than left to callers:

**Always answer.** Every method returns a decision. If the model is disabled,
missing, stale, slow, or throws, the deterministic rule engine answers instead
and the response records ``decision_source="rules"``. There is no code path
where a model failure becomes a failed request — a person who needs help does
not care why the model was unavailable.

**Never exceed the envelope.** Model output passes through
:class:`~ml.risk.safety.SafetyEnvelope` before it becomes a decision. This is
the second of three enforcement points; the database CHECK constraint is the
third.

**Load once.** Artefacts are loaded lazily and cached for the process lifetime.
Loading a scikit-learn model takes tens of milliseconds, which is unacceptable
per request and irrelevant per process.

**Log what cannot be recovered later.** Propensity, feature vector, model
version, and latency are captured at decision time and written to
``ml_decision_log``. None can be reconstructed afterwards, and off-policy
evaluation is impossible without them.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np

from core.config import settings
from ml.config import ACTIONS
from ml.features import FeatureVector, extract
from ml.registry import ModelRegistry, RegistryError
from ml.risk.safety import EnvelopeDecision, SafetyEnvelope

logger = logging.getLogger(__name__)

__all__ = ["AssistanceDecision", "InferenceService", "get_inference_service"]

RISK_MODEL = "risk_classifier"
BANDIT_MODEL = "assistance_bandit"
SEQUENCE_MODEL = "sequence_recommender"
ANOMALY_MODEL = "anomaly_detector"


@dataclass
class AssistanceDecision:
    """A complete policy decision, ready to persist and to explain."""

    risk_level: str
    assistance_mode: str
    capabilities: set[str]

    #: ``"model"`` or ``"rules"``. Never absent — every decision is attributable.
    decision_source: str
    model_version: str | None = None

    #: Calibrated P(elevated risk), when a model produced it.
    risk_score: float | None = None
    model_confidence: float | None = None

    #: True when the safety envelope reduced the model's proposal.
    envelope_clamped: bool = False

    #: Plain-language justifications shown to the helpee.
    reasons: list[str] = field(default_factory=list)

    #: P(chosen mode | context) under the deployed policy, for off-policy
    #: evaluation. ``None`` for deterministic rule decisions.
    propensity: float | None = None
    candidate_actions: list[str] = field(default_factory=list)

    #: The scored feature vector, for the decision log.
    features: dict[str, float] = field(default_factory=dict)
    latency_us: int = 0


class InferenceService:
    """Loads models on demand and produces safety-bounded decisions."""

    def __init__(self, registry: ModelRegistry | None = None) -> None:
        self.registry = registry or ModelRegistry()
        self._cache: dict[str, tuple[Any, Any]] = {}
        self._unavailable: set[str] = set()
        #: Propensity of the most recent bandit selection, carried from
        #: _propose_mode to decide() for the decision log.
        self._last_propensity: float | None = None

    # ------------------------------------------------------------------
    # Artefact access
    # ------------------------------------------------------------------

    def _get(self, name: str) -> tuple[Any, Any] | None:
        """Return ``(model, card)`` or ``None`` if unavailable.

        A model that failed to load once is recorded in ``_unavailable`` and not
        retried. Retrying a missing artefact on every request would add a
        filesystem stat and an exception to the hot path for no benefit — a
        model does not appear mid-process without a restart or an explicit
        :meth:`reload`.
        """
        if not settings.ML_ENABLED or name in self._unavailable:
            return None
        if name in self._cache:
            return self._cache[name]

        try:
            model, card = self.registry.load(name)
        except (RegistryError, Exception) as exc:  # noqa: BLE001
            logger.warning(
                "Model %r unavailable (%s); falling back to the rule engine.",
                name,
                exc,
            )
            self._unavailable.add(name)
            return None

        self._cache[name] = (model, card)
        logger.info("Loaded model %s version %s", name, card.version)
        return self._cache[name]

    def reload(self) -> None:
        """Drop cached artefacts so the next call picks up new versions."""
        self._cache.clear()
        self._unavailable.clear()

    def available_models(self) -> dict[str, str | None]:
        """Which models are published, for the health endpoint."""
        return {
            name: self.registry.current_version(name)
            for name in (RISK_MODEL, BANDIT_MODEL, SEQUENCE_MODEL, ANOMALY_MODEL)
        }

    # ------------------------------------------------------------------
    # The main decision
    # ------------------------------------------------------------------

    def decide(
        self,
        context: Any,
        *,
        app_profile: Mapping[str, float] | None = None,
        history: Mapping[str, float] | None = None,
        requested_capabilities: set[str] | None = None,
    ) -> AssistanceDecision:
        """Produce a policy decision for a live context.

        The pipeline: extract features → score risk → propose a mode → clamp to
        the safety envelope → intersect with what was requested. Any step may
        fail; each failure degrades to the rule engine rather than propagating.
        """
        started = time.perf_counter()

        if context is None:
            # No context reported at all. The conservative default is not
            # "assume safe" — it is voice guidance only, which is useful and
            # cannot expose anything.
            return self._rule_decision(
                context=None,
                reasons=[
                    "No device information was received, so only voice guidance "
                    "is available."
                ],
                started=started,
            )

        try:
            feature_vector = extract(
                context, app_profile=app_profile, history=history
            )
        except Exception as exc:  # noqa: BLE001 - never fail a live session
            logger.warning("Feature extraction failed (%s); using rules.", exc)
            return self._rule_decision(context, started=started)

        risk = self._score_risk(feature_vector)
        if risk is None:
            return self._rule_decision(
                context, features=feature_vector, started=started
            )

        prediction, version = risk

        if prediction.abstained:
            # The model is genuinely unsure. Handing an unsure decision to the
            # deterministic rules is better than acting on a coin flip, and it
            # is recorded as a rules decision so the abstention rate is
            # measurable in production, not just in evaluation.
            decision = self._rule_decision(
                context, features=feature_vector, started=started
            )
            decision.risk_score = prediction.probability
            decision.reasons.append(
                "The safety check was borderline, so the cautious setting was used."
            )
            return decision

        self._last_propensity = None
        proposed = self._propose_mode(feature_vector, prediction, context)
        envelope = SafetyEnvelope.apply(context, proposed)

        capabilities = self._capabilities_for(envelope.action, requested_capabilities)

        # The model may raise the risk level above what the rules saw, but never
        # lower it. A model that talks the system out of a protection the rules
        # identified is the exact failure this design forbids.
        risk_level = _max_risk(prediction.risk_level, envelope.rule_risk_level)

        return AssistanceDecision(
            risk_level=risk_level,
            assistance_mode=envelope.action,
            capabilities=capabilities,
            decision_source="model",
            model_version=version,
            risk_score=prediction.probability,
            model_confidence=prediction.confidence,
            envelope_clamped=envelope.clamped,
            reasons=envelope.reasons or _default_reasons(envelope.action),
            # Recorded only when the envelope did not override the choice: if
            # it did, the action taken is not the one the policy sampled, and
            # attaching the policy's propensity to it would corrupt every
            # importance weight computed from this row.
            propensity=None if envelope.clamped else self._last_propensity,
            candidate_actions=envelope.admissible_actions,
            features=feature_vector.as_dict(),
            latency_us=int((time.perf_counter() - started) * 1_000_000),
        )

    # ------------------------------------------------------------------
    # Components
    # ------------------------------------------------------------------

    def _score_risk(self, feature_vector: FeatureVector) -> tuple[Any, str] | None:
        """Score risk, or return ``None`` to fall back."""
        loaded = self._get(RISK_MODEL)
        if loaded is None:
            return None
        model, card = loaded
        try:
            return model.predict_one(feature_vector.as_array()), card.version
        except Exception as exc:  # noqa: BLE001
            logger.warning("Risk scoring failed (%s); using rules.", exc)
            self._unavailable.add(RISK_MODEL)
            return None

    def _propose_mode(
        self, feature_vector: FeatureVector, prediction: Any, context: Any
    ) -> str:
        """Choose a mode, using the bandit when one is published.

        Without a bandit the proposal is derived from the risk level alone,
        which is a reasonable default and identical to what the rules would
        pick at that risk level.
        """
        loaded = self._get(BANDIT_MODEL)
        admissible_names = SafetyEnvelope.admissible(context)

        if loaded is None:
            return admissible_names[-1] if admissible_names else "restricted"

        policy, _card = loaded
        mask = np.array([action in set(admissible_names) for action in ACTIONS])
        try:
            # select(), not argmax(probabilities()). Taking the argmax of the
            # action distribution is greedy exploitation, not Thompson
            # sampling: it removes exploration entirely and — because a
            # deterministic policy assigns propensity 1 to one action and 0 to
            # the rest — makes every logged decision useless for off-policy
            # evaluation. Sampling keeps both properties.
            decision = policy.select(feature_vector.as_array(), mask)
            self._last_propensity = decision.propensity
            return decision.action
        except Exception as exc:  # noqa: BLE001
            logger.warning("Bandit selection failed (%s); using ceiling.", exc)
            self._unavailable.add(BANDIT_MODEL)
            return admissible_names[-1] if admissible_names else "restricted"

    def recommend_actions(
        self, user_id: str, previous_action: str | None, *, k: int = 3
    ) -> list[dict[str, Any]]:
        """Rank likely next assistance actions. Empty list when unavailable."""
        loaded = self._get(SEQUENCE_MODEL)
        if loaded is None:
            return []
        model, card = loaded
        try:
            from ml.sequence.markov import START_TOKEN

            recommendations = model.recommend(
                user_id, previous_action or START_TOKEN, k=k
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Recommendation failed (%s).", exc)
            self._unavailable.add(SEQUENCE_MODEL)
            return []

        return [
            {
                "action": r.action,
                "probability": r.probability,
                "rank": r.rank,
                "source": r.source,
                "model_version": card.version,
            }
            for r in recommendations
        ]

    def score_anomaly(self, behaviour: np.ndarray) -> dict[str, Any] | None:
        """Score behavioural features for abuse. ``None`` when unavailable."""
        loaded = self._get(ANOMALY_MODEL)
        if loaded is None:
            return None
        model, card = loaded
        try:
            result = model.score_one(behaviour)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Anomaly scoring failed (%s).", exc)
            self._unavailable.add(ANOMALY_MODEL)
            return None
        return {
            "score": result.score,
            "is_anomalous": result.is_anomalous,
            "top_contributors": result.top_contributors,
            "model_version": card.version,
        }

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    def _rule_decision(
        self,
        context: Any,
        *,
        features: FeatureVector | None = None,
        reasons: list[str] | None = None,
        started: float | None = None,
    ) -> AssistanceDecision:
        """The deterministic decision, used whenever a model does not decide."""
        if context is None:
            mode = "voice"
            risk_level = "low"
            envelope_reasons = reasons or []
            candidates = ["restricted", "voice"]
        else:
            envelope = SafetyEnvelope.rule_only_mode(context)
            mode = envelope.action
            risk_level = envelope.rule_risk_level
            envelope_reasons = reasons or envelope.reasons or _default_reasons(mode)
            candidates = envelope.admissible_actions

        return AssistanceDecision(
            risk_level=risk_level,
            assistance_mode=mode,
            capabilities=self._capabilities_for(mode, None),
            decision_source="rules",
            reasons=envelope_reasons,
            candidate_actions=candidates,
            features=features.as_dict() if features else {},
            latency_us=(
                int((time.perf_counter() - started) * 1_000_000) if started else 0
            ),
        )

    @staticmethod
    def _capabilities_for(
        mode: str, requested: set[str] | None
    ) -> set[str]:
        """Capabilities a mode confers, intersected with what was asked for.

        Voice is always retained when the mode is not ``restricted``: the whole
        product is a person being talked through a problem, and silently
        dropping voice because a caller forgot to request it would break the
        core interaction.
        """
        from core.db.enums import MODE_CAPABILITIES

        granted = set(MODE_CAPABILITIES.get(mode, frozenset()))
        if requested:
            granted &= set(requested)
        if mode != "restricted":
            granted.add("voice")
        return granted


def _default_reasons(mode: str) -> list[str]:
    """Plain-language explanation when no restriction was applied."""
    if mode == "tap":
        return ["Your helper can talk, draw, and tap on your screen."]
    if mode in {"drawing", "pointer"}:
        return ["Your helper can talk and draw on your screen, but cannot tap."]
    if mode == "voice":
        return ["Your helper can talk to you, but cannot draw or tap."]
    return ["Your helper can see your screen but cannot interact with it."]


def _max_risk(a: str, b: str) -> str:
    """Return the more severe of two risk levels."""
    from core.db.enums import RISK_RANK

    return a if RISK_RANK.get(a, 0) >= RISK_RANK.get(b, 0) else b


_service: InferenceService | None = None


def get_inference_service() -> InferenceService:
    """Return the process-wide inference service."""
    global _service
    if _service is None:
        _service = InferenceService()
    return _service
