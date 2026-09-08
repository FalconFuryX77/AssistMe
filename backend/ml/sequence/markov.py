"""Next-action recommendation from assistance session sequences.

What this replaces
------------------
The inherited "intelligent assistance" recommended by counting: a
``(user, app, action)`` signature seen twice or more became a suggestion, ranked
by raw count and given a "confidence" of ``count / 4``. That system has no
notion of *order*, so it cannot answer the question a helper actually has —
"what usually comes next?" — only "what has this person done before?".

Two models are provided, deliberately unequal in sophistication:

**Backoff Markov chain** (this module). A first-order chain over assistance
actions with Katz-style backoff from a personal model to a population model to a
popularity prior. It is O(1) to update, needs no training run, and is
interpretable — a helper can be shown "after drawing, 42% of your sessions go to
remote control", which a neural model cannot offer.

**Neural sequence model** (:mod:`ml.sequence.neural`). An MLP over a windowed
history encoding, which can represent longer-range and non-linear dependencies
the first-order chain cannot.

The backoff chain is the default. The comparison in
``docs/ML_METHODOLOGY.md`` shows the neural model's advantage on this data is
small, and on a hot path in a safety-relevant system a small accuracy gain does
not justify an opaque model that needs a training pipeline and a GPU-shaped
dependency. Reporting that honestly is more useful than shipping the fancier
model because it is fancier.

Smoothing
---------
The reason the backoff exists: a user's personal transition matrix is almost
entirely zeros. With a median of a handful of sessions, most (previous, next)
pairs have never been observed, and maximum-likelihood estimation assigns them
probability zero — which is not "unlikely", it is "impossible", and it makes
the model unable to ever recommend an action the user has not already taken.
Backoff interpolates toward progressively coarser distributions so that
unobserved transitions retain positive probability, and the interpolation weight
is set by how much personal evidence exists (Jelinek–Mercer with a
count-dependent lambda).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np

__all__ = ["MarkovRecommender", "Recommendation", "START_TOKEN"]

#: Pseudo-state representing "before the first action of a session". Lets the
#: chain predict an opening action as well as a continuation.
START_TOKEN = "<start>"


@dataclass
class Recommendation:
    """One ranked suggestion."""

    action: str
    probability: float
    rank: int
    #: Which model level supplied most of the mass, for explainability.
    source: str


@dataclass
class MarkovRecommender:
    """First-order Markov chain with three-level backoff.

    Levels, from most to least specific:

    1. ``P(next | prev, user)`` — this person's own habits.
    2. ``P(next | prev)`` — how the population behaves after this action.
    3. ``P(next)`` — overall popularity, the cold-start fallback.
    """

    #: Interpolation strength. Higher means more evidence is needed before the
    #: personal model dominates. Chosen so that a user's own transitions carry
    #: roughly half the weight at five observations.
    smoothing: float = 5.0

    personal: dict[tuple[str, str], dict[str, float]] = field(default_factory=dict)
    population: dict[str, dict[str, float]] = field(default_factory=dict)
    popularity: dict[str, float] = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    def fit(
        self, sequences: Sequence[Sequence[str]], user_ids: Sequence[str]
    ) -> "MarkovRecommender":
        """Count transitions at all three levels."""
        personal: dict[tuple[str, str], dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        population: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        popularity: dict[str, float] = defaultdict(float)
        vocabulary: set[str] = set()

        for sequence, user in zip(sequences, user_ids):
            previous = START_TOKEN
            for action in sequence:
                personal[(user, previous)][action] += 1.0
                population[previous][action] += 1.0
                popularity[action] += 1.0
                vocabulary.add(action)
                previous = action

        self.personal = {k: dict(v) for k, v in personal.items()}
        self.population = {k: dict(v) for k, v in population.items()}
        self.popularity = dict(popularity)
        self.actions = sorted(vocabulary)
        return self

    def partial_fit(self, user_id: str, previous: str, action: str) -> None:
        """Incorporate one observed transition online.

        Lets the model improve within a live session rather than only at the
        next training run — which matters because the counts that make a
        personal model useful accumulate a handful at a time.
        """
        key = (user_id, previous)
        self.personal.setdefault(key, {})
        self.personal[key][action] = self.personal[key].get(action, 0.0) + 1.0
        self.population.setdefault(previous, {})
        self.population[previous][action] = (
            self.population[previous].get(action, 0.0) + 1.0
        )
        self.popularity[action] = self.popularity.get(action, 0.0) + 1.0
        if action not in self.actions:
            self.actions = sorted({*self.actions, action})

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def _normalise(self, counts: dict[str, float]) -> dict[str, float]:
        total = sum(counts.values())
        if total <= 0:
            return {}
        return {k: v / total for k, v in counts.items()}

    def distribution(self, user_id: str, previous: str) -> dict[str, float]:
        """Return the smoothed distribution over next actions.

        The Jelinek–Mercer weight ``λ = n / (n + smoothing)`` rises with the
        number of personal observations ``n``, so a user with no history is
        served entirely by the population model and one with many is served
        almost entirely by their own — a continuous handover rather than a
        threshold, which avoids the discontinuity where a user's suggestions
        change abruptly on their fifth session.
        """
        popularity = self._normalise(self.popularity)
        population = self._normalise(self.population.get(previous, {}))
        personal_counts = self.personal.get((user_id, previous), {})
        personal = self._normalise(personal_counts)

        n_personal = sum(personal_counts.values())
        n_population = sum(self.population.get(previous, {}).values())

        lambda_personal = n_personal / (n_personal + self.smoothing)
        lambda_population = n_population / (n_population + self.smoothing)

        distribution: dict[str, float] = {}
        for action in self.actions:
            base = popularity.get(action, 0.0)
            mixed_population = (
                lambda_population * population.get(action, 0.0)
                + (1 - lambda_population) * base
            )
            distribution[action] = (
                lambda_personal * personal.get(action, 0.0)
                + (1 - lambda_personal) * mixed_population
            )

        total = sum(distribution.values())
        if total <= 0:
            # Genuinely no evidence anywhere: a uniform distribution is the
            # honest answer, and returning an empty dict would make callers
            # handle a case that has a perfectly good default.
            uniform = 1.0 / max(1, len(self.actions))
            return {action: uniform for action in self.actions}
        return {k: v / total for k, v in distribution.items()}

    def recommend(
        self,
        user_id: str,
        previous: str = START_TOKEN,
        *,
        k: int = 3,
        allowed: Iterable[str] | None = None,
    ) -> list[Recommendation]:
        """Return the top-``k`` next actions.

        Args:
            user_id: Whose history to personalise with.
            previous: The last action taken, or :data:`START_TOKEN`.
            k: How many suggestions to return.
            allowed: Restrict to this set — used to intersect suggestions with
                the safety envelope's admissible actions, so the system never
                proposes something the helpee's policy would refuse. Suggesting
                an action and then blocking it is a worse experience than not
                suggesting it.
        """
        distribution = self.distribution(user_id, previous)
        if allowed is not None:
            allowed_set = set(allowed)
            distribution = {a: p for a, p in distribution.items() if a in allowed_set}
            total = sum(distribution.values())
            if total > 0:
                distribution = {a: p / total for a, p in distribution.items()}

        n_personal = sum(self.personal.get((user_id, previous), {}).values())
        n_population = sum(self.population.get(previous, {}).values())
        if n_personal >= self.smoothing:
            source = "personal_history"
        elif n_population > 0:
            source = "population_transitions"
        else:
            source = "popularity_prior"

        ranked = sorted(distribution.items(), key=lambda kv: -kv[1])[:k]
        return [
            Recommendation(action=action, probability=float(p), rank=i + 1, source=source)
            for i, (action, p) in enumerate(ranked)
        ]

    def score_matrix(
        self, user_ids: Sequence[str], previous_actions: Sequence[str]
    ) -> tuple[np.ndarray, list[str]]:
        """Score many contexts at once, for evaluation."""
        scores = np.zeros((len(user_ids), len(self.actions)))
        for i, (user, previous) in enumerate(zip(user_ids, previous_actions)):
            distribution = self.distribution(user, previous)
            for j, action in enumerate(self.actions):
                scores[i, j] = distribution.get(action, 0.0)
        return scores, list(self.actions)
