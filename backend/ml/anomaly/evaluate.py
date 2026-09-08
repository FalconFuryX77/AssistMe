"""Evaluation for the security anomaly detector.

Metric choice
-------------
The attack base rate is around 5%, so accuracy is meaningless — predicting
"normal" for everything scores 95%. Two metrics carry the assessment:

**Precision@k** is the operational metric. A human review queue has a fixed
capacity: if the team can look at fifty cases a day, what matters is how many of
the top fifty scores are genuine. That is precision@k, and it maps directly to
whether the queue is worth staffing. Recall at that same k is reported beside it,
because precision alone hides how much is being missed.

**ROC-AUC and PR-AUC** are threshold-free summaries. PR-AUC is the more
informative of the two under this class imbalance, and both are reported against
their no-skill baselines.

**Per-scenario recall** is reported separately for each injected attack type.
An aggregate number can hide that the detector catches every pairing-spam case
and no coercion case — and coercion is the scenario with the worst outcome for
the person, so a detector that misses it is not fit for purpose whatever its
average says.

An unsupervised detector is scored against labels it never saw. The labels exist
only in the evaluation, which is the point: the detector is not permitted to
learn from them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

__all__ = ["AnomalyEvaluation", "evaluate_detector"]


@dataclass
class AnomalyEvaluation:
    """Detection quality for one detector on a labelled test set."""

    n_samples: int
    n_anomalies: int
    base_rate: float

    roc_auc: float
    pr_auc: float
    pr_auc_no_skill: float

    #: At the detector's configured alert threshold.
    threshold: float
    alert_rate: float
    precision: float
    recall: float
    false_positive_rate: float

    #: Operational: fixed-capacity review queues.
    precision_at_k: dict[int, float] = field(default_factory=dict)
    recall_at_k: dict[int, float] = field(default_factory=dict)

    #: Recall broken down by injected attack scenario.
    per_scenario_recall: dict[str, float] = field(default_factory=dict)
    per_scenario_n: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        # JSON object keys must be strings.
        payload["precision_at_k"] = {str(k): v for k, v in self.precision_at_k.items()}
        payload["recall_at_k"] = {str(k): v for k, v in self.recall_at_k.items()}
        return payload


def evaluate_detector(
    detector: Any,
    features: np.ndarray,
    labels: np.ndarray,
    scenarios: list[str] | None = None,
    *,
    k_values: tuple[int, ...] = (25, 50, 100, 200),
) -> AnomalyEvaluation:
    """Score a fitted detector against held-out labels.

    Args:
        detector: A fitted :class:`~ml.anomaly.detector.AnomalyDetector`.
        features: Held-out behavioural vectors.
        labels: 1 for injected attacks, 0 for normal.
        scenarios: Per-row scenario names, for the breakdown.
        k_values: Review-queue capacities to report precision at.
    """
    scores = detector.score(features)
    threshold = getattr(detector, "threshold", float(np.quantile(scores, 0.98)))
    alerts = scores >= threshold

    true_positives = int(np.sum(alerts & (labels == 1)))
    false_positives = int(np.sum(alerts & (labels == 0)))
    false_negatives = int(np.sum(~alerts & (labels == 1)))
    true_negatives = int(np.sum(~alerts & (labels == 0)))

    precision = (
        true_positives / (true_positives + false_positives)
        if (true_positives + false_positives)
        else 0.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if (true_positives + false_negatives)
        else 0.0
    )
    false_positive_rate = (
        false_positives / (false_positives + true_negatives)
        if (false_positives + true_negatives)
        else 0.0
    )

    order = np.argsort(-scores)
    precision_at_k: dict[int, float] = {}
    recall_at_k: dict[int, float] = {}
    total_anomalies = int(np.sum(labels == 1))
    for k in k_values:
        if k > len(scores):
            continue
        top = order[:k]
        hits = int(np.sum(labels[top] == 1))
        precision_at_k[k] = hits / k
        recall_at_k[k] = hits / total_anomalies if total_anomalies else 0.0

    per_scenario_recall: dict[str, float] = {}
    per_scenario_n: dict[str, int] = {}
    if scenarios is not None:
        scenario_array = np.array(scenarios)
        for name in sorted(set(scenarios)):
            if name == "normal":
                continue
            mask = scenario_array == name
            per_scenario_n[name] = int(mask.sum())
            per_scenario_recall[name] = (
                float(np.mean(alerts[mask])) if mask.any() else 0.0
            )

    base_rate = float(np.mean(labels))

    return AnomalyEvaluation(
        n_samples=int(len(labels)),
        n_anomalies=total_anomalies,
        base_rate=base_rate,
        roc_auc=float(roc_auc_score(labels, scores)),
        pr_auc=float(average_precision_score(labels, scores)),
        pr_auc_no_skill=base_rate,
        threshold=float(threshold),
        alert_rate=float(np.mean(alerts)),
        precision=float(precision),
        recall=float(recall),
        false_positive_rate=float(false_positive_rate),
        precision_at_k=precision_at_k,
        recall_at_k=recall_at_k,
        per_scenario_recall=per_scenario_recall,
        per_scenario_n=per_scenario_n,
    )
