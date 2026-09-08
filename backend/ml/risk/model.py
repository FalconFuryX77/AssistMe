"""Calibrated risk classifier with cost-sensitive, abstaining decisions.

What replaces what
------------------
The inherited policy engine classified risk with a chain of ``if`` statements
over ``is_flag_secure_active`` and a hard-coded list of four app categories. It
returns one of three strings and nothing else: no probability, no uncertainty,
no way to tell a marginal call from an obvious one, and no way to measure
whether it is right.

This module replaces the *scoring* half of that with a probabilistic model, and
keeps the rule engine as the safety envelope (:mod:`ml.risk.safety`) and as the
fallback. Three properties matter more here than raw accuracy:

**Calibration.** A model that outputs 0.9 should be wrong one time in ten. This
is not a nicety: the decision layer thresholds the probability against an
explicit cost ratio, and a threshold applied to an uncalibrated score is
arithmetic on a meaningless number. Gradient-boosted trees are systematically
over-confident at the extremes, so the raw model is wrapped in isotonic
regression fitted on held-out folds
(:class:`~sklearn.calibration.CalibratedClassifierCV`), and calibration is
reported as expected calibration error and a reliability curve rather than
assumed.

**Cost sensitivity.** Deciding at ``p > 0.5`` implicitly asserts that failing to
protect someone costs the same as inconveniencing them. It does not. The
decision threshold is derived from :data:`~ml.config.COST_FALSE_SAFE` and
:data:`~ml.config.COST_FALSE_RISKY` — the Bayes-optimal threshold under
asymmetric costs is ``c_risky / (c_risky + c_safe)``, which for a 10:1 ratio is
0.091, not 0.5.

**Abstention.** In the band where the model is genuinely unsure, the right
answer is not a coin flip dressed as a prediction — it is to hand the decision
to the deterministic rules. The classifier reports abstention explicitly and
the abstention rate is a reported metric, because a model that abstains on 80%
of traffic has not solved the problem however good its accuracy on the rest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.config import COST_FALSE_RISKY, COST_FALSE_SAFE, seed_for
from ml.features import FEATURE_NAMES

__all__ = [
    "RiskClassifier",
    "RiskPrediction",
    "cost_optimal_threshold",
]


def cost_optimal_threshold(
    cost_false_safe: float = COST_FALSE_SAFE,
    cost_false_risky: float = COST_FALSE_RISKY,
) -> float:
    """Bayes-optimal decision threshold under asymmetric misclassification cost.

    Predicting "risky" is optimal when the expected cost of doing so is lower
    than the expected cost of not::

        (1 - p) · c_risky  <  p · c_safe
        ⟺  p  >  c_risky / (c_risky + c_safe)

    With the project's 10:1 ratio this is 0.091: the system restricts whenever
    there is more than roughly a 9% chance the context is sensitive. That is a
    deliberately cautious operating point, and expressing it as a formula over
    two named costs makes it arguable — the alternative, a hard-coded 0.5,
    encodes a 1:1 cost ratio that nobody ever chose.
    """
    return cost_false_risky / (cost_false_risky + cost_false_safe)


@dataclass
class RiskPrediction:
    """One scored context."""

    #: Calibrated P(elevated risk).
    probability: float
    #: Decision at the cost-optimal threshold.
    is_risky: bool
    #: Discrete level, for the ``risk_level`` column.
    risk_level: str
    #: True when the model declined to decide and the rules should be used.
    abstained: bool
    #: Distance from the decision boundary, normalised to [0, 1].
    confidence: float


class RiskClassifier:
    """Calibrated probabilistic risk model with a rule-based fallback contract.

    Two estimators are trained and the better-calibrated is selected:

    * **Logistic regression** — the interpretable baseline. Its coefficients are
      readable, it is naturally well-calibrated, and if it matches the ensemble
      it should be preferred: a simpler model on a safety path is worth real
      accuracy.
    * **Histogram gradient boosting** — captures the feature interactions the
      generative process contains and the rules cannot express (a critical app
      that is *also* actively protected; gesture capability amplifying the cost
      of a wrong call).

    Selection is by Brier score rather than accuracy, because the downstream
    decision is a thresholded probability and Brier score is the proper scoring
    rule for exactly that.
    """

    def __init__(
        self,
        *,
        abstain_cost_gap: float = 0.08,
        random_state: int | None = None,
    ) -> None:
        """
        Args:
            abstain_cost_gap: Abstain when the two actions' expected costs
                differ by less than this, in cost units. See
                :meth:`abstention_band` — the band is derived from the cost
                model rather than being a free parameter in probability units,
                which is what an arbitrary "±0.04 around the threshold" would
                be. In probability units that fixed margin spans a fifth of the
                usable range below a 0.09 threshold and sends most of the
                traffic to the fallback.
            random_state: Overrides the derived seed; for tests.
        """
        self.abstain_cost_gap = abstain_cost_gap
        self.random_state = (
            random_state if random_state is not None else seed_for("risk-classifier")
        )
        self.threshold = cost_optimal_threshold()
        self.model: Any = None
        self.model_name: str = "untrained"
        self.feature_names: list[str] = list(FEATURE_NAMES)
        self.training_metadata: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def _candidates(self) -> dict[str, Any]:
        """Build the candidate estimators, each wrapped in isotonic calibration.

        ``cv=5`` means calibration is fitted on out-of-fold predictions, so the
        calibrator never sees the same rows the base estimator was fitted on.
        Calibrating on training predictions is a classic and silent error: the
        base model is over-confident *and correct* in-sample, so the calibrator
        learns to leave it alone, and the resulting curve looks perfect on
        training data and is badly wrong on new data.
        """
        logistic = Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "clf",
                    LogisticRegression(
                        max_iter=2000,
                        C=1.0,
                        # Class weighting handles the base-rate imbalance;
                        # the asymmetric *cost* is handled separately at the
                        # threshold, so the two mechanisms stay independent.
                        class_weight="balanced",
                        random_state=self.random_state,
                    ),
                ),
            ]
        )
        boosting = HistGradientBoostingClassifier(
            max_iter=250,
            learning_rate=0.07,
            max_leaf_nodes=24,
            min_samples_leaf=30,
            l2_regularization=1.0,
            early_stopping=True,
            validation_fraction=0.15,
            random_state=self.random_state,
        )
        return {
            "logistic_regression": CalibratedClassifierCV(
                logistic, method="isotonic", cv=5
            ),
            "hist_gradient_boosting": CalibratedClassifierCV(
                boosting, method="isotonic", cv=5
            ),
        }

    def fit(self, features: np.ndarray, labels: np.ndarray) -> "RiskClassifier":
        """Fit both candidates and keep the better-calibrated one."""
        from sklearn.model_selection import StratifiedKFold, cross_val_predict

        best_name = None
        best_model = None
        best_brier = np.inf
        scores: dict[str, float] = {}

        folds = StratifiedKFold(
            n_splits=5, shuffle=True, random_state=self.random_state
        )

        for name, estimator in self._candidates().items():
            # Cross-validated probabilities give an honest estimate of the
            # calibration this model will have on unseen data.
            probabilities = cross_val_predict(
                estimator, features, labels, cv=folds, method="predict_proba"
            )[:, 1]
            brier = float(np.mean((probabilities - labels) ** 2))
            scores[name] = brier
            if brier < best_brier:
                best_brier = brier
                best_name = name
                best_model = estimator

        assert best_model is not None and best_name is not None
        best_model.fit(features, labels)

        self.model = best_model
        self.model_name = best_name
        self.training_metadata = {
            "selected_model": best_name,
            "selection_criterion": "cross-validated Brier score",
            "candidate_brier_scores": scores,
            "n_samples": int(features.shape[0]),
            "n_features": int(features.shape[1]),
            "positive_rate": float(np.mean(labels)),
            "decision_threshold": self.threshold,
            "abstain_cost_gap": self.abstain_cost_gap,
            "abstention_band": list(self.abstention_band()),
            "cost_false_safe": COST_FALSE_SAFE,
            "cost_false_risky": COST_FALSE_RISKY,
            "random_state": self.random_state,
        }
        return self

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """Calibrated P(elevated risk) for each row."""
        if self.model is None:
            raise RuntimeError("RiskClassifier has not been fitted")
        features = np.atleast_2d(features)
        return self.model.predict_proba(features)[:, 1]

    def predict(self, features: np.ndarray) -> np.ndarray:
        """Cost-sensitive binary decision for each row."""
        return (self.predict_proba(features) >= self.threshold).astype(int)

    def predict_one(self, feature_vector: np.ndarray) -> RiskPrediction:
        """Score a single context, with abstention and a discrete risk level."""
        probability = float(self.predict_proba(feature_vector.reshape(1, -1))[0])
        return self.interpret(probability)

    def abstention_band(self) -> tuple[float, float]:
        """The probability interval on which the model declines to decide.

        Derived from the cost model rather than chosen. The expected cost of
        each action at probability ``p`` is::

            cost(predict safe)  = p · c_false_safe
            cost(predict risky) = (1 - p) · c_false_risky

        and their difference is ``|p·(c_safe + c_risky) - c_risky|``. Where
        that difference is smaller than ``abstain_cost_gap`` the two decisions
        are near-equivalent in expected cost, so the model's opinion is not
        worth acting on and the deterministic rules — which are auditable and
        cannot regress — should decide instead.

        Solving for ``p`` gives a band centred on the threshold whose width
        scales with the costs, so changing the cost ratio moves the abstention
        region coherently instead of leaving a stale hand-tuned margin behind.
        """
        total = COST_FALSE_SAFE + COST_FALSE_RISKY
        half_width = self.abstain_cost_gap / total
        return (
            max(0.0, self.threshold - half_width),
            min(1.0, self.threshold + half_width),
        )

    def interpret(self, probability: float) -> RiskPrediction:
        """Turn a calibrated probability into a decision.

        Split out from :meth:`predict_one` so the mapping can be tested
        directly and reused when a probability arrives from elsewhere (a replay
        of a logged decision, for instance).
        """
        distance = abs(probability - self.threshold)
        low, high = self.abstention_band()
        abstained = low <= probability <= high
        is_risky = probability >= self.threshold

        # Confidence is distance from the boundary, scaled by how far the
        # boundary is from the nearer end of [0, 1] — so it reaches 1 only at a
        # probability of 0 or 1, and 0 exactly at the threshold.
        span = max(self.threshold, 1.0 - self.threshold)
        confidence = float(min(1.0, distance / span)) if span > 0 else 0.0

        return RiskPrediction(
            probability=probability,
            is_risky=is_risky,
            risk_level=self.risk_level(probability),
            abstained=abstained,
            confidence=confidence,
        )

    def risk_level(self, probability: float) -> str:
        """Map a probability to the three-valued ``risk_level`` column.

        The boundaries are the cost-optimal threshold (safe/medium) and a
        higher band where the model is confident enough that the rules would
        almost certainly agree (medium/high). Keeping the low boundary tied to
        the cost threshold means the discrete level and the binary decision can
        never disagree — a "low" row with ``is_risky`` set would be an
        incoherent record for an auditor to read.
        """
        if probability < self.threshold:
            return "low"
        if probability < 0.5:
            return "medium"
        return "high"

    # ------------------------------------------------------------------
    # Interpretability
    # ------------------------------------------------------------------

    def coefficients(self) -> dict[str, float] | None:
        """Logistic coefficients, when the selected model is the linear one.

        Returned for the model card. A safety-relevant model whose reasoning
        cannot be inspected is harder to defend, and when the linear model wins
        on Brier score its coefficients are the cheapest possible explanation
        of what it learned.
        """
        if self.model is None or self.model_name != "logistic_regression":
            return None
        try:
            weights = np.mean(
                [
                    fitted.estimator.named_steps["clf"].coef_[0]
                    for fitted in self.model.calibrated_classifiers_
                ],
                axis=0,
            )
        except (AttributeError, IndexError):  # pragma: no cover - sklearn internals
            return None
        return dict(zip(self.feature_names, (float(w) for w in weights)))
