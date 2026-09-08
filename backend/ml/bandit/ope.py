"""Off-policy evaluation: estimating a new policy's value from old logs.

The problem
-----------
A candidate assistance policy cannot be A/B tested by deploying it. The subjects
are elderly people, the actions grant a third party control of their phone, and
the harm from a bad policy is not a lost conversion — it is someone's bank
account. Any policy change must be assessed *before* it touches a real session.

Off-policy evaluation makes that possible: it estimates the value of a target
policy ``π`` from data logged under a different behaviour policy ``μ``, using
the propensities recorded at decision time.

The three estimators, and why all three
----------------------------------------
**IPS** (inverse propensity scoring) re-weights each logged reward by
``π(a|x)/μ(a|x)``. Unbiased whenever ``μ`` has full support, but its variance
explodes when the two policies disagree — a single action that ``μ`` took with
probability 0.01 and ``π`` would take with probability 1 contributes a weight of
100.

**SNIPS** (self-normalised IPS) divides by the mean importance weight instead of
by ``n``. This introduces a small bias and removes most of the variance, and it
also fixes IPS's embarrassing failure mode of estimating values outside the
reward range.

**DR** (doubly robust) combines a learned reward model with IPS on the model's
residuals. It is consistent if *either* the reward model or the propensities are
correct — hence "doubly robust" — and in practice has the lowest variance of the
three. It is the estimator to quote; the other two are reported alongside
because agreement among estimators with different failure modes is itself
evidence, and disagreement is a warning that the logs lack support.

Because these experiments run on a simulator, the *true* policy value is also
computable, so each estimator's error against ground truth is reported. That is
the point of doing this on synthetic data first: on real logs the truth is
unknowable and the estimators cannot be checked at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from ml.config import ACTIONS, seed_for

__all__ = [
    "OPEResult",
    "effective_sample_size",
    "evaluate_policy_offline",
    "true_policy_value",
]


@dataclass
class OPEResult:
    """Off-policy value estimates for one target policy."""

    policy_name: str

    ips: float
    ips_std_error: float
    snips: float
    dr: float
    dr_std_error: float

    #: Available only in simulation, where the reward table is known.
    true_value: float | None = None
    dr_absolute_error: float | None = None
    ips_absolute_error: float | None = None

    #: Diagnostics on whether the logs can support this estimate at all.
    effective_sample_size: float = 0.0
    max_importance_weight: float = 0.0
    mean_importance_weight: float = 0.0
    support_fraction: float = 1.0

    logged_policy_value: float = 0.0
    per_action_share: dict[str, float] = field(default_factory=dict)

    @property
    def improvement_over_logged(self) -> float:
        """Relative change in value against the policy that produced the logs."""
        if self.logged_policy_value == 0:
            return 0.0
        return (self.dr - self.logged_policy_value) / self.logged_policy_value


def effective_sample_size(weights: np.ndarray) -> float:
    """Kish's effective sample size, ``(Σw)² / Σw²``.

    Reports how many samples the importance-weighted estimate is *really* based
    on. Ten thousand logged decisions with an ESS of 40 give an estimate with
    the precision of forty samples, and quoting the estimate without the ESS
    hides that entirely. It is the first number to look at before believing any
    off-policy result.
    """
    total = float(np.sum(weights))
    if total == 0:
        return 0.0
    return float(total**2 / np.sum(weights**2))


def true_policy_value(
    policy: Any,
    features: np.ndarray,
    admissible: np.ndarray,
    reward_table: np.ndarray,
) -> float:
    """Exact expected value of a policy, using the simulator's reward table.

    Only computable in simulation. Used as the ground truth the estimators are
    scored against.
    """
    total = 0.0
    for i in range(len(features)):
        probabilities = policy.probabilities(features[i], admissible[i])
        total += float(probabilities @ reward_table[i])
    return total / len(features)


def _fit_reward_model(
    features: np.ndarray, actions: np.ndarray, rewards: np.ndarray
) -> Any:
    """Fit q̂(x, a), the reward model the DR estimator corrects against.

    The action index is appended as a feature rather than fitting one model per
    action: with five actions and an imbalanced logging policy, some actions
    have too few observations to fit a separate model, and a single model shares
    statistical strength across them.
    """
    design = np.hstack([features, actions.reshape(-1, 1)])
    model = HistGradientBoostingRegressor(
        max_iter=200,
        learning_rate=0.08,
        max_leaf_nodes=24,
        min_samples_leaf=20,
        random_state=seed_for("dr-reward-model"),
    )
    model.fit(design, rewards)
    return model


def _predict_all_actions(model: Any, features: np.ndarray) -> np.ndarray:
    """Return q̂ for every (context, action) pair as an ``(n, |A|)`` matrix."""
    n = len(features)
    predictions = np.zeros((n, len(ACTIONS)))
    for action_index in range(len(ACTIONS)):
        design = np.hstack(
            [features, np.full((n, 1), action_index, dtype=float)]
        )
        predictions[:, action_index] = model.predict(design)
    return predictions


def evaluate_policy_offline(
    policy: Any,
    features: np.ndarray,
    logged_actions: np.ndarray,
    logged_propensities: np.ndarray,
    logged_rewards: np.ndarray,
    admissible: np.ndarray,
    *,
    reward_table: np.ndarray | None = None,
    weight_clip: float = 50.0,
) -> OPEResult:
    """Estimate a target policy's value from logged bandit feedback.

    Args:
        policy: The target policy to evaluate.
        features: Logged contexts.
        logged_actions: Action indices taken by the behaviour policy.
        logged_propensities: ``μ(a|x)`` recorded at decision time.
        logged_rewards: Observed rewards for the taken actions only.
        admissible: Per-context safety mask.
        reward_table: Full counterfactual rewards, available in simulation only.
        weight_clip: Upper bound on importance weights.

    Note on clipping:
        Clipping trades a little bias for a large variance reduction, and
        without it a single tiny propensity can dominate the whole estimate.
        The proportion of clipped weights is reported through
        ``max_importance_weight`` and the effective sample size, so the
        trade-off is visible rather than silent.
    """
    n = len(features)

    target_probabilities = np.zeros((n, len(ACTIONS)))
    for i in range(n):
        target_probabilities[i] = policy.probabilities(features[i], admissible[i])

    taken_target_probability = target_probabilities[np.arange(n), logged_actions]

    # Guard against a zero or missing propensity in the logs. A logged action
    # with propensity zero is a logging bug — it says an action was taken that
    # the policy would never take — and must not silently become an infinite
    # weight.
    safe_propensities = np.maximum(logged_propensities, 1e-6)
    weights = np.clip(taken_target_probability / safe_propensities, 0.0, weight_clip)

    # --- IPS -----------------------------------------------------------
    ips_terms = weights * logged_rewards
    ips = float(np.mean(ips_terms))
    ips_std_error = float(np.std(ips_terms, ddof=1) / np.sqrt(n))

    # --- SNIPS ---------------------------------------------------------
    weight_sum = float(np.sum(weights))
    snips = float(np.sum(ips_terms) / weight_sum) if weight_sum > 0 else 0.0

    # --- DR ------------------------------------------------------------
    reward_model = _fit_reward_model(features, logged_actions, logged_rewards)
    q_hat = _predict_all_actions(reward_model, features)
    q_taken = q_hat[np.arange(n), logged_actions]
    # Direct-method term plus importance-weighted correction on the residual.
    direct = np.sum(target_probabilities * q_hat, axis=1)
    dr_terms = direct + weights * (logged_rewards - q_taken)
    dr = float(np.mean(dr_terms))
    dr_std_error = float(np.std(dr_terms, ddof=1) / np.sqrt(n))

    # --- Diagnostics ---------------------------------------------------
    # Support: the fraction of logged decisions where the target policy would
    # have had a non-trivial chance of taking the same action. Low support
    # means the estimate is extrapolating.
    support_fraction = float(np.mean(taken_target_probability > 1e-6))

    result = OPEResult(
        policy_name=getattr(policy, "name", policy.__class__.__name__),
        ips=ips,
        ips_std_error=ips_std_error,
        snips=snips,
        dr=dr,
        dr_std_error=dr_std_error,
        effective_sample_size=effective_sample_size(weights),
        max_importance_weight=float(np.max(weights)),
        mean_importance_weight=float(np.mean(weights)),
        support_fraction=support_fraction,
        logged_policy_value=float(np.mean(logged_rewards)),
        per_action_share={
            action: float(np.mean(target_probabilities[:, i]))
            for i, action in enumerate(ACTIONS)
        },
    )

    if reward_table is not None:
        truth = true_policy_value(policy, features, admissible, reward_table)
        result.true_value = truth
        result.dr_absolute_error = abs(dr - truth)
        result.ips_absolute_error = abs(ips - truth)

    return result
