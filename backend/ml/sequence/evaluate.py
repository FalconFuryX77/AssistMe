"""Rank-aware evaluation for next-action recommendation.

Metrics
-------
**Recall@k** — was the action actually taken among the top ``k`` suggestions?
The interface shows three suggestions, so Recall@3 is the metric that maps onto
what the user sees. Recall@1 is reported too, since a first suggestion that is
usually right is a materially different product from one that is usually third.

**MRR** — mean reciprocal rank. Rewards putting the right answer higher rather
than merely inside the window, which Recall@k cannot distinguish.

**NDCG@k** — discounts by log rank. Reported for comparability with the
recommender literature; on a single-relevant-item task it is a monotone
transform of MRR, so it adds little here and is included for convention rather
than insight.

Splitting
---------
The split is **by session, chronologically**, not by individual transition. A
random split over transitions would put a session's step 3 in training and its
step 4 in test, letting the model see the future of a sequence it is then asked
to predict. That leaks, and it inflates every metric. Splitting whole sessions
and holding out later ones matches how the model is actually used: trained on
what has happened, asked about what happens next.

Cold start is reported separately, because a recommender that works well only
for established users has not solved the problem for the population that needs
it most — a newly set up elderly user with no history at all.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

import numpy as np

from ml.sequence.markov import START_TOKEN

__all__ = ["SequenceEvaluation", "evaluate_recommender", "split_sessions"]


@dataclass
class SequenceEvaluation:
    """Ranking metrics for one recommender."""

    model_name: str
    n_predictions: int
    n_actions: int

    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    mrr: float
    ndcg_at_3: float

    #: Random-guess reference, given the vocabulary size.
    random_recall_at_3: float

    #: Metrics restricted to users with no prior history.
    cold_start_recall_at_3: float
    cold_start_n: int

    #: Metrics restricted to the first action of a session, the hardest case:
    #: nothing has happened yet, so only the user prior can inform the guess.
    first_action_recall_at_3: float
    first_action_n: int

    per_action_recall: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def split_sessions(
    sequences: Sequence[Sequence[str]],
    user_ids: Sequence[str],
    *,
    test_fraction: float = 0.25,
    cold_user_fraction: float = 0.15,
    seed_label: str = "sequence-split",
) -> tuple[list, list, list, list]:
    """Chronological session split, with a genuine cold-start population.

    Two things happen here, and both matter:

    **Chronological session split.** Sessions are in generation order, standing
    in for chronological order, and the last ``test_fraction`` are held out.
    Training therefore never contains a session that occurred after a test
    session — the constraint a production retraining schedule operates under.

    **User hold-out.** A fraction of users are removed from training entirely,
    so the test set contains people the model has never seen. Without this,
    every test user already has a personal history and the "cold start" column
    measures nothing: a purely chronological split gives all its test sessions
    to users who appear in training, which is the easy case and the one that
    matters least. New users are the population an assistance product acquires
    continuously, and an elderly user's very first session is precisely when
    good suggestions matter most.
    """
    import numpy as np

    from ml.config import seed_for

    generator = np.random.default_rng(seed_for(seed_label))
    unique_users = sorted(set(user_ids))
    n_cold = int(len(unique_users) * cold_user_fraction)
    cold_users = set(
        generator.choice(unique_users, size=n_cold, replace=False).tolist()
    ) if n_cold else set()

    split_at = int(len(sequences) * (1 - test_fraction))

    train_sequences: list = []
    train_users: list = []
    test_sequences: list = []
    test_users: list = []

    for index, (sequence, user) in enumerate(zip(sequences, user_ids)):
        if user in cold_users:
            # Held-out users contribute only to test, whenever they occurred.
            test_sequences.append(sequence)
            test_users.append(user)
        elif index < split_at:
            train_sequences.append(sequence)
            train_users.append(user)
        else:
            test_sequences.append(sequence)
            test_users.append(user)

    return train_sequences, train_users, test_sequences, test_users


def _dcg_at_k(rank: int, k: int) -> float:
    """Discounted gain for a single relevant item at ``rank`` (1-indexed)."""
    if rank > k:
        return 0.0
    return 1.0 / np.log2(rank + 1)


def evaluate_recommender(
    model: Any,
    train_sequences: Sequence[Sequence[str]],
    train_users: Sequence[str],
    test_sequences: Sequence[Sequence[str]],
    test_users: Sequence[str],
    *,
    model_name: str = "model",
    uses_full_history: bool = False,
) -> SequenceEvaluation:
    """Evaluate a fitted recommender on held-out sessions.

    Args:
        model: Anything exposing ``score_matrix(users, contexts)``.
        train_sequences / train_users: Used only to identify cold-start users.
        test_sequences / test_users: The held-out sessions.
        model_name: Label for the results table.
        uses_full_history: True for models taking the whole prefix (neural),
            False for first-order models taking only the previous action.
    """
    seen_users = set(train_users)

    contexts: list[Any] = []
    users: list[str] = []
    targets: list[str] = []
    is_cold: list[bool] = []
    is_first: list[bool] = []

    for sequence, user in zip(test_sequences, test_users):
        history: list[str] = []
        for position, action in enumerate(sequence):
            contexts.append(
                list(history) if uses_full_history else (history[-1] if history else START_TOKEN)
            )
            users.append(user)
            targets.append(action)
            is_cold.append(user not in seen_users)
            is_first.append(position == 0)
            history.append(action)

    if not contexts:
        raise ValueError("no test transitions to evaluate")

    scores, action_vocabulary = model.score_matrix(users, contexts)
    index_of = {action: i for i, action in enumerate(action_vocabulary)}

    n = len(targets)
    ranks = np.full(n, len(action_vocabulary) + 1, dtype=float)

    for i, target in enumerate(targets):
        column = index_of.get(target)
        if column is None:
            # The target action never appeared in training. Left at the
            # sentinel rank, which counts as a miss at every k — the honest
            # treatment, since the model genuinely could not have suggested it.
            continue
        order = np.argsort(-scores[i])
        ranks[i] = float(np.where(order == column)[0][0] + 1)

    cold = np.array(is_cold)
    first = np.array(is_first)

    def recall_at(k: int, mask: np.ndarray | None = None) -> float:
        selected = ranks if mask is None else ranks[mask]
        if len(selected) == 0:
            return 0.0
        return float(np.mean(selected <= k))

    per_action: dict[str, float] = {}
    target_array = np.array(targets)
    for action in action_vocabulary:
        mask = target_array == action
        if mask.any():
            per_action[action] = float(np.mean(ranks[mask] <= 3))

    return SequenceEvaluation(
        model_name=model_name,
        n_predictions=n,
        n_actions=len(action_vocabulary),
        recall_at_1=recall_at(1),
        recall_at_3=recall_at(3),
        recall_at_5=recall_at(5),
        mrr=float(np.mean(1.0 / ranks)),
        ndcg_at_3=float(np.mean([_dcg_at_k(int(r), 3) for r in ranks])),
        random_recall_at_3=float(min(1.0, 3.0 / max(1, len(action_vocabulary)))),
        cold_start_recall_at_3=recall_at(3, cold) if cold.any() else 0.0,
        cold_start_n=int(cold.sum()),
        first_action_recall_at_3=recall_at(3, first),
        first_action_n=int(first.sum()),
        per_action_recall=per_action,
    )
