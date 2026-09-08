"""Contextual bandit policies for assistance-mode selection.

Why a bandit and not a classifier
----------------------------------
Mode selection has no ground-truth label. Nobody can say what the "correct"
assistance mode for a session was; there is only what *happened* when a mode was
chosen — did the helper resolve the problem, did the helpee revoke control, did
the session end in success. That is bandit feedback: one action taken, one
reward observed, and no information about the alternatives.

Framing it as supervised learning would require inventing labels, and the
invented label would be whatever the current rule engine chose, which teaches a
model to imitate the system it is meant to improve on.

The two policies
----------------
**LinUCB** (Li et al., WWW 2010) maintains a ridge regression of reward on
context per action and adds a confidence bonus proportional to the predictive
standard deviation, so an action tried rarely in a given region of context space
is optimistically favoured. It has a sublinear regret guarantee under a linear
reward assumption.

**Thompson sampling** maintains a Bayesian posterior over each action's weights
and samples from it, exploring in proportion to genuine posterior uncertainty.
It typically performs at least as well as UCB empirically and — the property
that decides it here — its action probabilities are well-defined, which is what
lets a decision be logged with a propensity and evaluated off-policy later.

Safety
------
Both policies select only from the admissible set supplied by
:class:`~ml.risk.safety.SafetyEnvelope`. An inadmissible action is never
explored, never scored, and never assigned probability mass. This is the
difference between a bandit that is safe by construction and one that is safe
because a filter happens to run afterwards: exploration bonuses cannot push the
policy toward an action it is not allowed to take, because that action is not in
the argmax at all.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from ml.config import ACTIONS, seed_for

__all__ = [
    "BanditDecision",
    "EpsilonGreedyPolicy",
    "LinUCBPolicy",
    "MaxPrivilegePolicy",
    "Policy",
    "RandomPolicy",
    "LeastPrivilegePolicy",
    "ThompsonSamplingPolicy",
]


@dataclass
class BanditDecision:
    """One action selection, with everything needed to evaluate it later."""

    action_index: int
    action: str
    #: P(this action | context) under the policy that chose it. Recorded at
    #: decision time because it is unrecoverable afterwards.
    propensity: float
    #: Full probability vector over all actions, zero for inadmissible ones.
    probabilities: np.ndarray
    #: The policy's estimated reward for the chosen action.
    expected_reward: float


class Policy(ABC):
    """Interface every policy implements, learned or baseline."""

    name: str = "policy"

    @abstractmethod
    def probabilities(self, context: np.ndarray, admissible: np.ndarray) -> np.ndarray:
        """Return P(action | context), zero outside the admissible set."""

    def select(
        self,
        context: np.ndarray,
        admissible: np.ndarray,
        *,
        need_propensity: bool = True,
    ) -> BanditDecision:
        """Sample an action according to the policy's own distribution.

        ``need_propensity`` exists because for most policies the action
        distribution is cheap, but for Thompson sampling it costs a Monte Carlo
        estimate that choosing an action does not require. Simulation loops
        that only need the action pass ``False``; the production path, which
        must log a propensity for later off-policy evaluation, leaves it True.
        """
        probabilities = self.probabilities(context, admissible)
        generator = getattr(self, "_generator", None)
        if generator is None:
            generator = np.random.default_rng(seed_for(f"select-{self.name}"))
            self._generator = generator
        index = int(generator.choice(len(ACTIONS), p=probabilities))
        return BanditDecision(
            action_index=index,
            action=ACTIONS[index],
            propensity=float(probabilities[index]),
            probabilities=probabilities,
            expected_reward=float(self.expected_reward(context, index)),
        )

    def expected_reward(self, context: np.ndarray, action_index: int) -> float:
        """The policy's own estimate of the reward. Zero for policies without one."""
        return 0.0

    def update(self, context: np.ndarray, action_index: int, reward: float) -> None:
        """Incorporate an observed reward. No-op for stateless baselines."""


def _uniform_over(admissible: np.ndarray) -> np.ndarray:
    """Uniform distribution over the admissible actions."""
    probabilities = np.zeros(len(ACTIONS))
    allowed = np.flatnonzero(admissible)
    if len(allowed) == 0:
        # Defensive: "restricted" is admissible in every context by
        # construction, so an empty set means a caller passed a bad mask.
        probabilities[0] = 1.0
        return probabilities
    probabilities[allowed] = 1.0 / len(allowed)
    return probabilities


class RandomPolicy(Policy):
    """Uniform over admissible actions. The floor any policy must beat."""

    name = "random"

    def probabilities(self, context: np.ndarray, admissible: np.ndarray) -> np.ndarray:
        return _uniform_over(admissible)


class LeastPrivilegePolicy(Policy):
    """Always take the least-privileged admissible action.

    The conservative baseline. It is maximally safe and often unhelpful, which
    is exactly the trade-off the learned policy has to improve on — a policy
    that only matched this one would be evidence that learning added nothing.
    """

    name = "least_privilege"

    def probabilities(self, context: np.ndarray, admissible: np.ndarray) -> np.ndarray:
        probabilities = np.zeros(len(ACTIONS))
        allowed = np.flatnonzero(admissible)
        probabilities[allowed[0] if len(allowed) else 0] = 1.0
        return probabilities


class MaxPrivilegePolicy(Policy):
    """Always take the most-privileged admissible action.

    The rule engine's behaviour: it takes its own ceiling. Included as the
    baseline the learned policy is actually competing with in production.
    """

    name = "rule_ceiling"

    def probabilities(self, context: np.ndarray, admissible: np.ndarray) -> np.ndarray:
        probabilities = np.zeros(len(ACTIONS))
        allowed = np.flatnonzero(admissible)
        probabilities[allowed[-1] if len(allowed) else 0] = 1.0
        return probabilities


class _LinearBandit(Policy):
    """Shared ridge-regression machinery for LinUCB and Thompson sampling.

    Per action ``a`` the model keeps ``A_a = λI + Σ x xᵀ`` and ``b_a = Σ r x``,
    giving the ridge solution ``θ_a = A_a⁻¹ b_a``.

    ``A_a`` is maintained in its Cholesky-free inverse form and updated with the
    Sherman–Morrison identity, so each update is O(d²) rather than the O(d³) of
    re-inverting. With 36 features and a decision on the hot path of a live
    session, that is the difference between microseconds and milliseconds.
    """

    def __init__(self, n_features: int, *, alpha: float = 1.0, ridge: float = 1.0, seed_label: str = "bandit"):
        self.n_features = n_features
        self.alpha = alpha
        self.ridge = ridge
        self.n_actions = len(ACTIONS)
        self.A_inv = np.array(
            [np.eye(n_features) / ridge for _ in range(self.n_actions)]
        )
        self.b = np.zeros((self.n_actions, n_features))
        self._generator = np.random.default_rng(seed_for(seed_label))

    def theta(self, action_index: int) -> np.ndarray:
        return self.A_inv[action_index] @ self.b[action_index]

    def expected_reward(self, context: np.ndarray, action_index: int) -> float:
        return float(self.theta(action_index) @ context)

    def uncertainty(self, context: np.ndarray, action_index: int) -> float:
        """Predictive standard deviation, ``sqrt(xᵀ A⁻¹ x)``."""
        return float(np.sqrt(max(0.0, context @ self.A_inv[action_index] @ context)))

    def update(self, context: np.ndarray, action_index: int, reward: float) -> None:
        """Sherman–Morrison rank-one update of the inverse Gram matrix."""
        A_inv = self.A_inv[action_index]
        Ax = A_inv @ context
        denominator = 1.0 + context @ Ax
        self.A_inv[action_index] = A_inv - np.outer(Ax, Ax) / denominator
        self.b[action_index] += reward * context


class LinUCBPolicy(_LinearBandit):
    """LinUCB with disjoint per-action models.

    Scores ``θᵀx + α·sqrt(xᵀA⁻¹x)`` and takes the argmax over admissible
    actions. ``α`` controls the optimism: larger explores more.

    LinUCB is deterministic, which is a problem for off-policy evaluation —
    a deterministic policy assigns propensity 1 to one action and 0 to the rest,
    so importance weights are undefined wherever the logging policy disagreed.
    :meth:`probabilities` therefore mixes in a small uniform component over the
    admissible set, which both keeps every propensity strictly positive and
    reflects what a deployment would actually do (some exploration is required
    for the logs to remain useful for the *next* policy).
    """

    name = "linucb"

    def __init__(self, n_features: int, *, alpha: float = 0.6, exploration: float = 0.05, **kwargs):
        super().__init__(n_features, alpha=alpha, seed_label="linucb", **kwargs)
        self.exploration = exploration

    def scores(self, context: np.ndarray, admissible: np.ndarray) -> np.ndarray:
        scores = np.full(len(ACTIONS), -np.inf)
        for index in np.flatnonzero(admissible):
            scores[index] = self.expected_reward(context, index) + self.alpha * self.uncertainty(
                context, index
            )
        return scores

    def probabilities(self, context: np.ndarray, admissible: np.ndarray) -> np.ndarray:
        allowed = np.flatnonzero(admissible)
        if len(allowed) == 0:
            return _uniform_over(admissible)

        best = int(np.argmax(self.scores(context, admissible)))
        probabilities = np.zeros(len(ACTIONS))
        probabilities[allowed] = self.exploration / len(allowed)
        probabilities[best] += 1.0 - self.exploration
        return probabilities


class ThompsonSamplingPolicy(_LinearBandit):
    """Linear Thompson sampling with a Gaussian posterior per action.

    Draws ``θ̃_a ~ N(θ̂_a, v²A_a⁻¹)`` and takes the argmax of ``θ̃ᵀx``. Because
    the action is chosen by a random draw, the policy is genuinely stochastic
    and its action probabilities are estimable — :meth:`probabilities` does so
    by Monte Carlo, which is exact in the limit and cheap enough at the sample
    count used here.

    That estimate matters beyond evaluation: it is the ``propensity`` column of
    ``ml_decision_log``, and every off-policy estimate computed later divides by
    it.
    """

    name = "thompson"

    def __init__(self, n_features: int, *, v: float = 0.25, n_probability_samples: int = 256, **kwargs):
        super().__init__(n_features, seed_label="thompson", **kwargs)
        self.v = v
        self.n_probability_samples = n_probability_samples

    def _sample_scores(
        self,
        context: np.ndarray,
        admissible: np.ndarray,
        generator,
        n_samples: int = 1,
    ) -> np.ndarray:
        """Draw ``n_samples`` posterior score vectors, shape ``(n, |A|)``.

        Batched deliberately. Sampling ``θ̃ ~ N(θ̂, v²A⁻¹)`` needs a factor of
        the covariance, and drawing one sample at a time recomputes that factor
        every single time — for a 36-dimensional posterior that is an O(d³)
        Cholesky per draw. Estimating a propensity from 128 draws over four
        admissible actions then costs 512 decompositions *per decision*, which
        made off-policy evaluation over 10,000 logged rows take minutes.

        Only the *score* ``θ̃ᵀx`` is needed, and it is a scalar. So rather than
        sampling the full weight vector, sample the scalar directly:

            θ̃ᵀx  ~  N( θ̂ᵀx ,  v² · xᵀA⁻¹x )

        which is exact, needs no factorisation at all, and reduces each draw to
        two dot products already computed for the mean and the uncertainty.
        """
        scores = np.full((n_samples, len(ACTIONS)), -np.inf)
        for index in np.flatnonzero(admissible):
            mean = self.expected_reward(context, index)
            std = self.v * self.uncertainty(context, index)
            scores[:, index] = generator.normal(mean, std, size=n_samples)
        return scores

    def select(
        self,
        context: np.ndarray,
        admissible: np.ndarray,
        *,
        need_propensity: bool = True,
    ) -> BanditDecision:
        """Draw once from the posterior and take the argmax.

        This *is* Thompson sampling: one posterior draw, one greedy choice
        against it. The base implementation would instead estimate the action
        distribution by Monte Carlo and then sample from that estimate —
        equivalent in distribution, but spending ``n_probability_samples``
        multivariate draws to reproduce what a single draw already gives.

        The Monte Carlo estimate is still needed for the *propensity*, which is
        why ``need_propensity`` exists: a simulation loop that needs only the
        action skips it and runs orders of magnitude faster, while the
        production path pays for it once per decision and gets a logged
        propensity that makes the decision evaluable later.
        """
        allowed = np.flatnonzero(admissible)
        if len(allowed) == 0:
            return super().select(
                context, admissible, need_propensity=need_propensity
            )

        scores = self._sample_scores(context, admissible, self._generator)[0]
        index = int(np.argmax(scores))

        if need_propensity:
            probabilities = self.probabilities(context, admissible)
            propensity = float(probabilities[index])
        else:
            # Not estimated. NaN rather than 1.0 so that a caller which logs it
            # anyway produces an obviously broken importance weight instead of
            # a plausible-looking wrong one.
            probabilities = np.zeros(len(ACTIONS))
            probabilities[index] = 1.0
            propensity = float("nan")

        return BanditDecision(
            action_index=index,
            action=ACTIONS[index],
            propensity=propensity,
            probabilities=probabilities,
            expected_reward=float(self.expected_reward(context, index)),
        )

    def probabilities(self, context: np.ndarray, admissible: np.ndarray) -> np.ndarray:
        """Monte Carlo estimate of P(action | context).

        Needed for the ``propensity`` column of ``ml_decision_log``, without
        which no off-policy estimator can be computed later. Not needed to
        *choose* an action — see :meth:`select`.
        """
        allowed = np.flatnonzero(admissible)
        if len(allowed) == 0:
            return _uniform_over(admissible)

        draws = self._sample_scores(
            context, admissible, self._generator, self.n_probability_samples
        )
        winners = np.argmax(draws, axis=1)
        counts = np.bincount(winners, minlength=len(ACTIONS)).astype(float)

        probabilities = counts / counts.sum()
        # Floor every admissible action's probability. A Monte Carlo estimate of
        # zero is not evidence the true probability is zero, and a zero
        # propensity makes an importance weight infinite — one such row can
        # dominate an entire IPS estimate.
        floor = 1e-3
        probabilities[allowed] = np.maximum(probabilities[allowed], floor)
        probabilities[~admissible.astype(bool)] = 0.0
        return probabilities / probabilities.sum()


class EpsilonGreedyPolicy(Policy):
    """Epsilon-greedy over a shared linear reward model.

    The simplest thing that could work, kept as a baseline so the reported gain
    from LinUCB and Thompson sampling is measured against a real alternative
    rather than only against random.
    """

    name = "epsilon_greedy"

    def __init__(self, n_features: int, *, epsilon: float = 0.1, learning_rate: float = 0.05):
        self.epsilon = epsilon
        self.learning_rate = learning_rate
        self.weights = np.zeros((len(ACTIONS), n_features))
        self._generator = np.random.default_rng(seed_for("epsilon-greedy"))

    def expected_reward(self, context: np.ndarray, action_index: int) -> float:
        return float(self.weights[action_index] @ context)

    def probabilities(self, context: np.ndarray, admissible: np.ndarray) -> np.ndarray:
        allowed = np.flatnonzero(admissible)
        if len(allowed) == 0:
            return _uniform_over(admissible)
        estimates = np.array([self.expected_reward(context, i) for i in allowed])
        best = allowed[int(np.argmax(estimates))]
        probabilities = np.zeros(len(ACTIONS))
        probabilities[allowed] = self.epsilon / len(allowed)
        probabilities[best] += 1.0 - self.epsilon
        return probabilities

    def update(self, context: np.ndarray, action_index: int, reward: float) -> None:
        error = reward - self.expected_reward(context, action_index)
        self.weights[action_index] += self.learning_rate * error * context
