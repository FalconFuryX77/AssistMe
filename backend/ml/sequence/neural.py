"""Neural sequence baseline, and the honest comparison against the Markov chain.

This model exists to answer a question rather than to be deployed: *does a model
capable of representing longer-range and non-linear dependencies actually beat
the first-order chain on this data?* Reporting that comparison is worth more
than assuming either answer.

Architecture: a multi-layer perceptron over a windowed history encoding — the
last ``window`` actions, one-hot encoded and position-weighted, concatenated
with the user's own action histogram. That is deliberately modest. On a corpus
of a few thousand short sessions over seven action types, a recurrent or
attention model has far more capacity than the data can identify, and would
mostly demonstrate that it can overfit.

The position weighting (exponential decay toward older actions) is what lets a
fixed-width input carry ordering information without a recurrent architecture.

If this model does not clearly beat the Markov chain, the Markov chain is the
right thing to ship: it is interpretable, updates online in O(1), has no
training pipeline, and adds no dependency to the request path. That conclusion
is recorded in the methodology document either way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
from sklearn.neural_network import MLPClassifier

from ml.config import seed_for
from ml.sequence.markov import START_TOKEN

__all__ = ["NeuralSequenceRecommender"]


@dataclass
class NeuralSequenceRecommender:
    """MLP over a decayed window of recent actions plus a user histogram."""

    window: int = 4
    hidden_layer_sizes: tuple[int, ...] = (64, 32)
    decay: float = 0.6

    actions: list[str] = field(default_factory=list)
    users: list[str] = field(default_factory=list)
    model: MLPClassifier | None = None
    _action_index: dict[str, int] = field(default_factory=dict)
    _user_histograms: dict[str, np.ndarray] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Encoding
    # ------------------------------------------------------------------

    def _encode(self, history: Sequence[str], user_id: str) -> np.ndarray:
        """Encode a history window and the user's overall action histogram.

        Recent actions are weighted more heavily than older ones by
        ``decay ** age``, which gives a fixed-length vector an ordering signal.
        Without it the encoding would be a bag of recent actions and the model
        could not distinguish "drew, then took control" from the reverse.
        """
        n_actions = len(self.actions)
        window_vector = np.zeros(n_actions)

        recent = list(history)[-self.window :]
        for age, action in enumerate(reversed(recent)):
            index = self._action_index.get(action)
            if index is not None:
                window_vector[index] += self.decay**age

        histogram = self._user_histograms.get(user_id)
        if histogram is None:
            # An unseen user contributes a uniform histogram rather than zeros:
            # all-zeros would be indistinguishable from "a user who has done
            # nothing", which is a different and less common situation.
            histogram = np.full(n_actions, 1.0 / max(1, n_actions))

        return np.concatenate([window_vector, histogram])

    def _build_user_histograms(
        self, sequences: Sequence[Sequence[str]], user_ids: Sequence[str]
    ) -> None:
        counts: dict[str, np.ndarray] = {}
        for sequence, user in zip(sequences, user_ids):
            vector = counts.setdefault(user, np.zeros(len(self.actions)))
            for action in sequence:
                index = self._action_index.get(action)
                if index is not None:
                    vector[index] += 1.0
        self._user_histograms = {
            user: (vector / vector.sum() if vector.sum() else vector)
            for user, vector in counts.items()
        }

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    def fit(
        self, sequences: Sequence[Sequence[str]], user_ids: Sequence[str]
    ) -> "NeuralSequenceRecommender":
        vocabulary = sorted({action for sequence in sequences for action in sequence})
        self.actions = vocabulary
        self._action_index = {action: i for i, action in enumerate(vocabulary)}
        self.users = sorted(set(user_ids))
        self._build_user_histograms(sequences, user_ids)

        rows: list[np.ndarray] = []
        targets: list[int] = []
        for sequence, user in zip(sequences, user_ids):
            history: list[str] = []
            for action in sequence:
                rows.append(self._encode(history, user))
                targets.append(self._action_index[action])
                history.append(action)

        if not rows:
            return self

        self.model = MLPClassifier(
            hidden_layer_sizes=self.hidden_layer_sizes,
            activation="relu",
            solver="adam",
            alpha=1e-3,
            max_iter=400,
            early_stopping=True,
            n_iter_no_change=15,
            validation_fraction=0.12,
            random_state=seed_for("neural-sequence"),
        )
        self.model.fit(np.vstack(rows), np.array(targets))
        return self

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def distribution(self, user_id: str, history: Sequence[str]) -> dict[str, float]:
        """Return P(next action) for a user and their session so far."""
        if self.model is None:
            uniform = 1.0 / max(1, len(self.actions))
            return {action: uniform for action in self.actions}

        encoded = self._encode(history, user_id).reshape(1, -1)
        probabilities = self.model.predict_proba(encoded)[0]

        # MLPClassifier only emits classes it saw in training; map back through
        # ``classes_`` rather than assuming the output is aligned with the full
        # vocabulary, which it need not be.
        distribution = {action: 0.0 for action in self.actions}
        for class_index, probability in zip(self.model.classes_, probabilities):
            distribution[self.actions[int(class_index)]] = float(probability)
        return distribution

    def score_matrix(
        self, user_ids: Sequence[str], histories: Sequence[Sequence[str]]
    ) -> tuple[np.ndarray, list[str]]:
        """Score many contexts at once, for evaluation."""
        if self.model is None:
            return np.zeros((len(user_ids), len(self.actions))), list(self.actions)
        encoded = np.vstack(
            [self._encode(history, user) for user, history in zip(user_ids, histories)]
        )
        raw = self.model.predict_proba(encoded)
        scores = np.zeros((len(user_ids), len(self.actions)))
        for column, class_index in enumerate(self.model.classes_):
            scores[:, int(class_index)] = raw[:, column]
        return scores, list(self.actions)


class PopularityRecommender:
    """Always recommend the globally most frequent actions.

    The baseline every recommender must beat to have earned its complexity. It
    is included because a personalised model that cannot beat "suggest the most
    common thing" has not demonstrated personalisation, only overhead — and
    that outcome is common enough in recommender work to be worth guarding
    against explicitly.
    """

    name = "popularity"

    def __init__(self) -> None:
        self.actions: list[str] = []
        self._probabilities: np.ndarray = np.array([])

    def fit(
        self, sequences: Sequence[Sequence[str]], user_ids: Sequence[str]
    ) -> "PopularityRecommender":
        counts: dict[str, float] = {}
        for sequence in sequences:
            for action in sequence:
                counts[action] = counts.get(action, 0.0) + 1.0
        self.actions = sorted(counts)
        total = sum(counts.values()) or 1.0
        self._probabilities = np.array([counts[a] / total for a in self.actions])
        return self

    def score_matrix(
        self, user_ids: Sequence[str], histories: Sequence[Sequence[str]]
    ) -> tuple[np.ndarray, list[str]]:
        return (
            np.tile(self._probabilities, (len(user_ids), 1)),
            list(self.actions),
        )
