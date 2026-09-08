"""Online simulation and regret analysis for the bandit policies.

Regret, and why it is the right measure
----------------------------------------
Cumulative regret is the total reward lost against an oracle that always picks
the best admissible action::

    R(T) = Σₜ [ r(xₜ, a*ₜ) − r(xₜ, aₜ) ]

It answers the question that matters for a deployed learner: *how much does
learning cost while it is still learning?* A policy that eventually converges to
optimal but explores expensively for ten thousand sessions is not deployable
here — every exploratory step is a real assistance session for a real person.

Sublinear regret is the property to look for. Flat cumulative regret means the
policy has converged; linear growth means it is still paying a constant price
per round and has not learned.

Every reported curve is averaged over independent seeds with a confidence band,
because a single run of a stochastic policy is an anecdote. The seeds are
derived through :func:`~ml.config.seed_for` so the whole thing reproduces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from ml.config import ACTIONS, seed_for

__all__ = ["RegretResult", "compare_policies", "simulate_online"]


@dataclass
class RegretResult:
    """Averaged regret curve and summary statistics for one policy."""

    policy_name: str
    n_rounds: int
    n_seeds: int

    #: Mean cumulative regret at each round, averaged over seeds.
    mean_cumulative_regret: list[float]
    #: Standard error at each round.
    std_error: list[float]

    final_regret: float
    final_regret_std: float
    #: Mean regret per round over the last 20% of rounds. Near zero means
    #: converged; a persistent positive value means the policy has plateaued
    #: short of optimal.
    terminal_regret_rate: float

    mean_reward: float
    oracle_mean_reward: float
    #: Fraction of rounds where the optimal admissible action was chosen.
    optimal_action_rate: float

    action_distribution: dict[str, float] = field(default_factory=dict)
    #: Count of times an inadmissible action was selected. Must be zero.
    safety_violations: int = 0


def simulate_online(
    policy_factory: Callable[[], Any],
    features: np.ndarray,
    admissible: np.ndarray,
    reward_table: np.ndarray,
    *,
    n_rounds: int | None = None,
    n_seeds: int = 5,
    label: str = "regret",
) -> RegretResult:
    """Run a policy online against the simulator and measure regret.

    Args:
        policy_factory: Builds a *fresh* policy. Called once per seed — reusing
            one instance would let a later run start from an earlier run's
            learned state and report regret that looks far better than it is.
        features: Context matrix.
        admissible: Per-context safety mask.
        reward_table: Ground-truth expected rewards.
        n_rounds: Rounds per seed. Defaults to the whole dataset.
        n_seeds: Independent repetitions.
        label: Seed-derivation label.

    Returns:
        A :class:`RegretResult` averaged over seeds.
    """
    n_rounds = n_rounds or len(features)
    n_rounds = min(n_rounds, len(features))

    all_curves = np.zeros((n_seeds, n_rounds))
    all_rewards = np.zeros(n_seeds)
    all_oracle = np.zeros(n_seeds)
    optimal_hits = np.zeros(n_seeds)
    action_counts = np.zeros(len(ACTIONS))
    violations = 0

    for seed_index in range(n_seeds):
        generator = np.random.default_rng(seed_for(f"{label}-{seed_index}"))
        policy = policy_factory()
        # Give each seed a different presentation order, so the curve reflects
        # the policy rather than one fixed sequence of contexts.
        order = generator.permutation(len(features))[:n_rounds]

        cumulative = 0.0
        rewards_sum = 0.0
        oracle_sum = 0.0

        for t, row in enumerate(order):
            context = features[row]
            mask = admissible[row]

            # need_propensity=False: regret uses only the chosen action, and
            # estimating the action distribution as well would dominate the
            # runtime of the Thompson arm for no benefit to the measurement.
            decision = policy.select(context, mask, need_propensity=False)

            if not mask[decision.action_index]:
                violations += 1

            allowed = np.flatnonzero(mask)
            best_value = float(np.max(reward_table[row, allowed]))
            chosen_value = float(reward_table[row, decision.action_index])

            cumulative += best_value - chosen_value
            all_curves[seed_index, t] = cumulative
            rewards_sum += chosen_value
            oracle_sum += best_value
            action_counts[decision.action_index] += 1
            if np.isclose(chosen_value, best_value):
                optimal_hits[seed_index] += 1

            # A stochastic (Bernoulli) reward, matching what a real deployment
            # observes. Feeding the policy the true expectation would make
            # learning easier than it is in practice.
            observed = float(generator.random() < chosen_value)
            policy.update(context, decision.action_index, observed)

        all_rewards[seed_index] = rewards_sum / n_rounds
        all_oracle[seed_index] = oracle_sum / n_rounds
        optimal_hits[seed_index] /= n_rounds

    mean_curve = all_curves.mean(axis=0)
    std_error = all_curves.std(axis=0, ddof=1) / np.sqrt(n_seeds) if n_seeds > 1 else np.zeros(n_rounds)

    tail_start = int(n_rounds * 0.8)
    tail_regret = mean_curve[-1] - mean_curve[tail_start]
    tail_rounds = max(1, n_rounds - tail_start)

    total_actions = action_counts.sum()

    return RegretResult(
        policy_name=getattr(policy, "name", policy.__class__.__name__),
        n_rounds=n_rounds,
        n_seeds=n_seeds,
        mean_cumulative_regret=[float(v) for v in mean_curve],
        std_error=[float(v) for v in std_error],
        final_regret=float(mean_curve[-1]),
        final_regret_std=float(all_curves[:, -1].std(ddof=1)) if n_seeds > 1 else 0.0,
        terminal_regret_rate=float(tail_regret / tail_rounds),
        mean_reward=float(all_rewards.mean()),
        oracle_mean_reward=float(all_oracle.mean()),
        optimal_action_rate=float(optimal_hits.mean()),
        action_distribution={
            action: float(action_counts[i] / total_actions) if total_actions else 0.0
            for i, action in enumerate(ACTIONS)
        },
        safety_violations=int(violations),
    )


def compare_policies(
    factories: dict[str, Callable[[], Any]],
    features: np.ndarray,
    admissible: np.ndarray,
    reward_table: np.ndarray,
    *,
    n_rounds: int = 4000,
    n_seeds: int = 5,
) -> dict[str, RegretResult]:
    """Run every policy through the same simulation and return their results."""
    return {
        name: simulate_online(
            factory,
            features,
            admissible,
            reward_table,
            n_rounds=n_rounds,
            n_seeds=n_seeds,
            label=f"regret-{name}",
        )
        for name, factory in factories.items()
    }
