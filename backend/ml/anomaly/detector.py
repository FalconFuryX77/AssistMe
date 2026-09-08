"""Unsupervised detection of abusive assistance behaviour.

The threat this addresses
--------------------------
Every other control in AssistMe assumes the helper is who the helpee thinks they
are. Pairing requires consent, escalation requires an explicit risk screen, and
the audit ledger records everything. None of that helps when the helpee has been
persuaded — by a phone call from "the bank", by a fake support line — to approve
a stranger and then to approve control. Consent obtained by deception is still
consent as far as the schema is concerned.

Fraud against older adults follows recognisable behavioural signatures, and
those signatures are visible in data this system already collects: how many
pairing requests an account sends, how quickly it asks for control after
connecting, how long sessions run and at what hour, how new the account is.

Why unsupervised
----------------
There are no labelled fraud cases. There cannot be at this stage — the system
has no users — and even in production, confirmed fraud labels arrive rarely,
long after the fact, and are systematically biased toward the cases someone
noticed. A supervised model trained on those labels would learn to detect the
fraud that has already been caught.

Unsupervised detection asks a different and more tractable question: *is this
behaviour unlike the overwhelming majority of legitimate behaviour?* It needs no
labels, and it can flag a novel pattern that no historical label describes.

The ensemble
------------
**Isolation Forest** isolates points by random splits; anomalies need fewer
splits, because they sit in sparse regions. It is fast, handles mixed scales
after standardisation, and makes no distributional assumption.

**Mahalanobis distance** measures deviation from the multivariate mean in units
of the covariance. It catches a different failure mode: a point whose every
individual feature is unremarkable but whose *combination* is impossible — a
brand-new account running a four-hour session at 3 a.m., where neither fact
alone is odd. Isolation Forest, splitting on one axis at a time, is comparatively
weak on exactly those correlation-violating points.

The two scores are combined by rank averaging rather than by averaging raw
values, since they live on incomparable scales and rank averaging needs no
tuning constant that would silently become stale.

What this is not
----------------
An anomaly score is **not evidence of fraud**. It is a signal to surface a
second confirmation to the helpee, or to route a case for review. Nothing in
this module blocks a session or accuses anyone, and the operating point is
chosen for a low false-positive rate precisely because the cost of wrongly
telling someone their daughter looks like a fraudster is high.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.covariance import MinCovDet
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from ml.config import seed_for

__all__ = ["AnomalyDetector", "AnomalyScore"]


@dataclass
class AnomalyScore:
    """One scored behavioural observation."""

    #: Combined score in [0, 1]. Higher is more anomalous.
    score: float
    is_anomalous: bool
    isolation_score: float
    mahalanobis_score: float
    #: Features furthest from normal, for the review queue. An unexplained
    #: alert is one a human cannot act on.
    top_contributors: list[tuple[str, float]] = field(default_factory=list)


class AnomalyDetector:
    """Rank-averaged ensemble of Isolation Forest and robust Mahalanobis distance."""

    def __init__(
        self,
        *,
        contamination: float = 0.02,
        n_estimators: int = 300,
        alert_quantile: float = 0.95,
    ) -> None:
        """
        Args:
            contamination: Isolation Forest's assumed anomaly rate. Set below
                the true injected rate deliberately — over-stating
                contamination makes the forest carve out normal regions as
                anomalous, and in production the true rate is unknown and
                certainly low.
            n_estimators: Trees in the forest.
            alert_quantile: Training-set score quantile that becomes the alert
                threshold. 0.95 targets roughly a 5% alert rate, chosen to sit
                just above the expected attack base rate: a threshold below the
                base rate caps achievable recall no matter how good the scores
                are, which is a property of the operating point rather than of
                the detector. Precision and recall at other capacities are
                reported by the evaluation as a full precision@k table rather
                than assumed.
        """
        self.contamination = contamination
        self.alert_quantile = alert_quantile
        self.random_state = seed_for("anomaly-detector")

        self.scaler = StandardScaler()
        self.forest = IsolationForest(
            n_estimators=n_estimators,
            contamination=contamination,
            random_state=self.random_state,
            n_jobs=-1,
        )
        self.covariance: MinCovDet | None = None
        self.feature_names: list[str] = []
        self.threshold: float = 1.0
        self._train_isolation: np.ndarray = np.array([])
        self._train_mahalanobis: np.ndarray = np.array([])
        self._train_mean: np.ndarray = np.array([])
        self._train_std: np.ndarray = np.array([])

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    def fit(
        self, features: np.ndarray, feature_names: list[str] | None = None
    ) -> "AnomalyDetector":
        """Fit on data assumed to be predominantly normal.

        The training set is *not* filtered to known-normal rows, because in
        production no such filter exists. Both estimators are robust to a small
        contamination fraction: the forest by design, and the covariance by
        using the Minimum Covariance Determinant estimator, which fits on the
        most concentrated subset and so is not dragged outward by outliers the
        way an ordinary sample covariance would be.
        """
        self.feature_names = feature_names or [
            f"feature_{i}" for i in range(features.shape[1])
        ]
        scaled = self.scaler.fit_transform(features)

        self.forest.fit(scaled)
        # Negated so that larger means more anomalous, matching Mahalanobis.
        self._train_isolation = -self.forest.score_samples(scaled)

        try:
            self.covariance = MinCovDet(
                support_fraction=0.9, random_state=self.random_state
            ).fit(scaled)
            self._train_mahalanobis = np.sqrt(
                np.maximum(0.0, self.covariance.mahalanobis(scaled))
            )
        except (ValueError, np.linalg.LinAlgError):
            # Singular covariance (a constant or collinear feature). Degrading
            # to the forest alone is correct: a silently broken second opinion
            # is worse than an honest single one.
            self.covariance = None
            self._train_mahalanobis = np.zeros(len(scaled))

        self._train_mean = scaled.mean(axis=0)
        self._train_std = np.where(scaled.std(axis=0) > 0, scaled.std(axis=0), 1.0)

        combined = self._combine(self._train_isolation, self._train_mahalanobis)
        self.threshold = float(np.quantile(combined, self.alert_quantile))
        return self

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _rank_normalise(self, values: np.ndarray, reference: np.ndarray) -> np.ndarray:
        """Map values to their quantile within the training distribution.

        Rank normalisation puts both detectors on a common [0, 1] scale without
        assuming either is Gaussian or bounded, and without a scaling constant
        that would need re-tuning whenever the feature set changes.
        """
        if len(reference) == 0:
            return np.zeros(len(values))
        return np.searchsorted(np.sort(reference), values, side="right") / len(reference)

    def _combine(self, isolation: np.ndarray, mahalanobis: np.ndarray) -> np.ndarray:
        if self.covariance is None:
            return self._rank_normalise(isolation, self._train_isolation) if len(
                self._train_isolation
            ) else isolation
        isolation_rank = self._rank_normalise(isolation, self._train_isolation)
        mahalanobis_rank = self._rank_normalise(mahalanobis, self._train_mahalanobis)
        return 0.5 * isolation_rank + 0.5 * mahalanobis_rank

    def score(self, features: np.ndarray) -> np.ndarray:
        """Return combined anomaly scores in [0, 1] for each row."""
        scaled = self.scaler.transform(np.atleast_2d(features))
        isolation = -self.forest.score_samples(scaled)
        if self.covariance is not None:
            mahalanobis = np.sqrt(np.maximum(0.0, self.covariance.mahalanobis(scaled)))
        else:
            mahalanobis = np.zeros(len(scaled))
        return self._combine(isolation, mahalanobis)

    def score_one(self, feature_row: np.ndarray) -> AnomalyScore:
        """Score a single observation, with per-feature attribution."""
        row = np.atleast_2d(feature_row)
        scaled = self.scaler.transform(row)
        isolation = float(-self.forest.score_samples(scaled)[0])
        mahalanobis = (
            float(np.sqrt(max(0.0, self.covariance.mahalanobis(scaled)[0])))
            if self.covariance is not None
            else 0.0
        )
        combined = float(self._combine(np.array([isolation]), np.array([mahalanobis]))[0])

        deviations = np.abs((scaled[0] - self._train_mean) / self._train_std)
        order = np.argsort(-deviations)[:3]
        contributors = [
            (self.feature_names[i], float(deviations[i])) for i in order
        ]

        return AnomalyScore(
            score=combined,
            is_anomalous=combined >= self.threshold,
            isolation_score=isolation,
            mahalanobis_score=mahalanobis,
            top_contributors=contributors,
        )
