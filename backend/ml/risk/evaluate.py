"""Evaluation for the risk classifier: discrimination, calibration, and cost.

Why these metrics and not accuracy
-----------------------------------
Elevated-risk contexts are roughly a quarter of traffic in the simulator and
would be rarer in reality. A model that predicts "safe" for everything scores
well on accuracy and is worthless — worse than worthless, since it is exactly
the failure the product cannot tolerate. Accuracy is reported here only for
familiarity, always next to the majority-class baseline that contextualises it.

The metrics that carry the argument:

* **PR-AUC** over ROC-AUC as the headline discrimination measure. With an
  imbalanced positive class, ROC-AUC is dominated by the many true negatives
  and stays flattering; precision-recall reflects performance on the class that
  matters. Both are reported, with the no-skill baselines.
* **Brier score and ECE** for calibration. The decision layer thresholds a
  probability, so the probability has to mean something. ECE is computed with
  equal-frequency bins rather than equal-width: with a threshold at 0.09 most
  predictions cluster near zero, and equal-width bins would put nearly every
  sample in the first bin and report a meaningless number.
* **Expected cost** at the operating point, under the declared 10:1 ratio.
  This is the metric the system is actually optimised for, and the one on which
  the learned policy is compared against the rule baseline.
* **Recall on the two adversarial subpopulations** — benign-critical contexts
  (where rules over-restrict) and hidden-sensitive contexts (where rules
  under-protect). These are the cases the research exists to address, so
  aggregate numbers that average them away are not evidence of anything.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    log_loss,
    roc_auc_score,
)

from ml.config import COST_FALSE_RISKY, COST_FALSE_SAFE

__all__ = [
    "CalibrationCurve",
    "RiskEvaluation",
    "evaluate_risk_model",
    "expected_calibration_error",
    "reliability_curve",
]


@dataclass
class CalibrationCurve:
    """Reliability data: mean predicted probability against observed frequency."""

    bin_lower: list[float]
    bin_upper: list[float]
    mean_predicted: list[float]
    observed_frequency: list[float]
    count: list[int]


@dataclass
class RiskEvaluation:
    """Full evaluation of a risk model against a held-out set."""

    n_samples: int
    positive_rate: float

    # Discrimination
    roc_auc: float
    pr_auc: float
    pr_auc_no_skill: float

    # Calibration
    brier_score: float
    brier_score_baseline: float
    log_loss: float
    expected_calibration_error: float
    max_calibration_error: float

    # Operating point
    threshold: float
    accuracy: float
    majority_class_accuracy: float
    bayes_accuracy: float | None
    precision: float
    recall: float
    specificity: float
    f1: float
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int

    # Cost
    expected_cost_per_decision: float
    expected_cost_at_half_threshold: float
    cost_reduction_vs_half: float

    # Abstention
    abstention_rate: float
    accuracy_when_deciding: float

    # Subpopulations where the rule engine is known to be wrong
    subgroup_metrics: dict[str, dict[str, float]] = field(default_factory=dict)

    calibration_curve: CalibrationCurve | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.calibration_curve is not None:
            payload["calibration_curve"] = asdict(self.calibration_curve)
        return payload


def reliability_curve(
    labels: np.ndarray, probabilities: np.ndarray, n_bins: int = 10
) -> CalibrationCurve:
    """Equal-frequency reliability curve.

    Equal-frequency (quantile) binning is used deliberately. With a decision
    threshold near 0.09, the predicted-probability distribution is heavily
    concentrated below 0.2; equal-width bins would place almost every sample in
    the first bin, leaving the remaining bins empty and the reported calibration
    error dominated by noise from a handful of points.
    """
    order = np.argsort(probabilities)
    sorted_probabilities = probabilities[order]
    sorted_labels = labels[order]

    edges = np.linspace(0, len(probabilities), n_bins + 1).astype(int)

    lower: list[float] = []
    upper: list[float] = []
    predicted: list[float] = []
    observed: list[float] = []
    counts: list[int] = []

    for i in range(n_bins):
        start, stop = edges[i], edges[i + 1]
        if stop <= start:
            continue
        chunk_probabilities = sorted_probabilities[start:stop]
        chunk_labels = sorted_labels[start:stop]
        lower.append(float(chunk_probabilities[0]))
        upper.append(float(chunk_probabilities[-1]))
        predicted.append(float(np.mean(chunk_probabilities)))
        observed.append(float(np.mean(chunk_labels)))
        counts.append(int(stop - start))

    return CalibrationCurve(
        bin_lower=lower,
        bin_upper=upper,
        mean_predicted=predicted,
        observed_frequency=observed,
        count=counts,
    )


def expected_calibration_error(
    labels: np.ndarray, probabilities: np.ndarray, n_bins: int = 10
) -> tuple[float, float]:
    """Return ``(ECE, MCE)`` from an equal-frequency reliability curve.

    ECE is the sample-weighted mean absolute gap between predicted and observed
    frequency; MCE is the worst single bin. Both are needed: a model can have a
    small average error while being badly wrong in the one bin that straddles
    the decision threshold, which is the bin that determines behaviour.
    """
    curve = reliability_curve(labels, probabilities, n_bins=n_bins)
    total = sum(curve.count)
    if total == 0:
        return 0.0, 0.0
    gaps = [
        abs(p - o) for p, o in zip(curve.mean_predicted, curve.observed_frequency)
    ]
    ece = sum(g * c for g, c in zip(gaps, curve.count)) / total
    return float(ece), float(max(gaps) if gaps else 0.0)


def _cost(labels: np.ndarray, predictions: np.ndarray) -> float:
    """Mean misclassification cost under the declared asymmetric costs."""
    false_safe = np.sum((labels == 1) & (predictions == 0))
    false_risky = np.sum((labels == 0) & (predictions == 1))
    total = len(labels)
    return float(
        (false_safe * COST_FALSE_SAFE + false_risky * COST_FALSE_RISKY) / total
    )


def evaluate_risk_model(
    classifier: Any,
    features: np.ndarray,
    labels: np.ndarray,
    *,
    contexts: list[Any] | None = None,
    bayes_accuracy: float | None = None,
) -> RiskEvaluation:
    """Evaluate a fitted :class:`~ml.risk.model.RiskClassifier`.

    Args:
        classifier: The fitted model.
        features: Held-out feature matrix.
        labels: Held-out labels.
        contexts: Held-out context records, used to compute subgroup metrics on
            the populations where rules are known to fail.
        bayes_accuracy: The simulator's achievable accuracy ceiling, reported
            alongside model accuracy so the latter is interpretable.
    """
    probabilities = classifier.predict_proba(features)
    threshold = classifier.threshold
    predictions = (probabilities >= threshold).astype(int)

    tn, fp, fn, tp = confusion_matrix(labels, predictions, labels=[0, 1]).ravel()

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    specificity = tn / (tn + fp) if (tn + fp) else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )

    positive_rate = float(np.mean(labels))
    majority_accuracy = max(positive_rate, 1.0 - positive_rate)

    ece, mce = expected_calibration_error(labels, probabilities)

    # Abstention band, derived from the classifier's own cost model.
    if hasattr(classifier, "abstention_band"):
        low, high = classifier.abstention_band()
        abstained = (probabilities >= low) & (probabilities <= high)
    else:  # pragma: no cover - baselines that never abstain
        abstained = np.zeros(len(probabilities), dtype=bool)
    deciding = ~abstained
    accuracy_when_deciding = (
        float(np.mean(predictions[deciding] == labels[deciding]))
        if deciding.any()
        else 0.0
    )

    cost_at_operating_point = _cost(labels, predictions)
    cost_at_half = _cost(labels, (probabilities >= 0.5).astype(int))

    subgroups: dict[str, dict[str, float]] = {}
    if contexts is not None:
        subgroups = _subgroup_metrics(contexts, labels, predictions, probabilities)

    return RiskEvaluation(
        n_samples=int(len(labels)),
        positive_rate=positive_rate,
        roc_auc=float(roc_auc_score(labels, probabilities)),
        pr_auc=float(average_precision_score(labels, probabilities)),
        pr_auc_no_skill=positive_rate,
        brier_score=float(brier_score_loss(labels, probabilities)),
        # A model predicting the base rate for everything. Any Brier score
        # above this means the model is worse than knowing nothing.
        brier_score_baseline=float(positive_rate * (1 - positive_rate)),
        log_loss=float(log_loss(labels, np.clip(probabilities, 1e-9, 1 - 1e-9))),
        expected_calibration_error=ece,
        max_calibration_error=mce,
        threshold=float(threshold),
        accuracy=float(np.mean(predictions == labels)),
        majority_class_accuracy=float(majority_accuracy),
        bayes_accuracy=bayes_accuracy,
        precision=float(precision),
        recall=float(recall),
        specificity=float(specificity),
        f1=float(f1),
        true_positives=int(tp),
        false_positives=int(fp),
        true_negatives=int(tn),
        false_negatives=int(fn),
        expected_cost_per_decision=cost_at_operating_point,
        expected_cost_at_half_threshold=cost_at_half,
        cost_reduction_vs_half=(
            float((cost_at_half - cost_at_operating_point) / cost_at_half)
            if cost_at_half
            else 0.0
        ),
        abstention_rate=float(np.mean(abstained)),
        accuracy_when_deciding=accuracy_when_deciding,
        subgroup_metrics=subgroups,
        calibration_curve=reliability_curve(labels, probabilities),
    )


def _subgroup_metrics(
    contexts: list[Any],
    labels: np.ndarray,
    predictions: np.ndarray,
    probabilities: np.ndarray,
) -> dict[str, dict[str, float]]:
    """Metrics on the populations where the rule engine is known to be wrong.

    ``hidden_sensitive`` contexts carry sensitive content in an app whose
    category does not reveal it — the rules under-protect, so **recall** is the
    metric of interest. ``benign_critical`` contexts are critical-category apps
    showing nothing sensitive — the rules over-restrict, so the **false
    positive rate** is the metric of interest. Reporting only the aggregate
    would hide both.
    """
    masks = {
        "hidden_sensitive": np.array(
            [bool(getattr(c, "is_hidden_sensitive", False)) for c in contexts]
        ),
        "benign_critical": np.array(
            [bool(getattr(c, "is_benign_critical", False)) for c in contexts]
        ),
    }

    results: dict[str, dict[str, float]] = {}
    for name, mask in masks.items():
        if not mask.any():
            continue
        subgroup_labels = labels[mask]
        subgroup_predictions = predictions[mask]
        positives = subgroup_labels == 1
        negatives = subgroup_labels == 0
        results[name] = {
            "n": int(mask.sum()),
            "positive_rate": float(np.mean(subgroup_labels)),
            "recall": float(
                np.mean(subgroup_predictions[positives]) if positives.any() else 0.0
            ),
            "false_positive_rate": float(
                np.mean(subgroup_predictions[negatives]) if negatives.any() else 0.0
            ),
            "mean_predicted_probability": float(np.mean(probabilities[mask])),
            "accuracy": float(np.mean(subgroup_predictions == subgroup_labels)),
        }
    return results
