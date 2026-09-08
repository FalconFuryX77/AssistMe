"""Synthetic data generators with explicit, documented generative processes.

Read this before believing any number this package reports
-----------------------------------------------------------
AssistMe has no deployed user base, so there is no observational corpus of
elderly people receiving remote assistance. Every result in
``docs/ML_METHODOLOGY.md`` is therefore computed on data produced here, and the
honest framing matters more than the numbers:

**What these experiments can establish.** That the modelling approach is
implemented correctly; that calibration, cost-sensitive thresholding and
off-policy evaluation behave as the theory says on data whose ground truth is
known; that the learned policy dominates the rule baseline *on contexts where
the rule baseline is known to be wrong*; and that the safety envelope is never
violated. These are claims about the method and the implementation, and
synthetic data is a legitimate — indeed the only — way to check them, because
the ground-truth labels and the true propensities are knowable by construction.

**What they cannot establish.** Any claim about real-world accuracy. The
generative process below encodes the author's beliefs about how risk arises;
a model evaluated on data drawn from those beliefs will confirm them. Reported
accuracies are properties of this simulator, not of the world, and are labelled
as such throughout. Validating against real usage is the primary item in
"future work", not a detail.

The generative process
----------------------
Contexts are drawn from a long-tailed app-category distribution with realistic
correlations (banking apps set ``FLAG_SECURE`` far more often than media apps).
A latent continuous sensitivity ``s`` is formed from those signals, and the risk
label is drawn through a logistic link on ``s`` rather than assigned by
threshold. Three properties of this design are deliberate:

1. **The Bayes-optimal classifier is not the rule engine.** If labels were a
   deterministic function of ``is_flag_secure_active`` and category, the rules
   would already be optimal and there would be nothing to learn. Instead ``s``
   depends on interactions the rules do not encode.

2. **Rules are wrong in identifiable ways.** Two populations are injected: a
   *benign critical app* (a banking app on its login splash, no sensitive data
   on screen) where the rule engine over-restricts, and *sensitive content in a
   non-critical app* (a photographed bank card in a messaging thread) where the
   rule engine under-protects. These are the cases the research is about.

3. **Labels carry noise.** A fixed proportion of labels are flipped, so no
   classifier can reach 100% and reported accuracy has a meaningful ceiling.
   The Bayes rate is computed and reported alongside model performance, because
   "94% accurate" is uninterpretable without knowing that the achievable
   maximum is 95%.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final

import numpy as np

from ml.config import ACTIONS, rng
from ml.features import APP_CATEGORIES, CRITICAL_CATEGORIES

__all__ = [
    "ContextRecord",
    "RiskDataset",
    "SequenceDataset",
    "BanditLogDataset",
    "SecurityDataset",
    "generate_bandit_logs",
    "generate_risk_dataset",
    "generate_security_dataset",
    "generate_sequence_dataset",
]

# Marginal distribution over foreground-app categories. Long-tailed: people
# spend most of their time in a few apps, and the categories that matter most
# for risk are among the rarest — which is why accuracy on the majority class
# is not an informative metric here.
_CATEGORY_WEIGHTS: Final[dict[str, float]] = {
    "messaging": 0.26,
    "social": 0.17,
    "media": 0.13,
    "productivity": 0.12,
    "system": 0.11,
    "unknown": 0.09,
    "banking": 0.055,
    "health": 0.03,
    "payment": 0.025,
    "password_manager": 0.01,
}

# P(FLAG_SECURE active | category). Banking and password apps set it almost
# always; media apps set it for DRM content; messaging almost never.
_FLAG_SECURE_RATE: Final[dict[str, float]] = {
    "banking": 0.88,
    "payment": 0.82,
    "password_manager": 0.95,
    "health": 0.45,
    "media": 0.12,
    "system": 0.05,
    "messaging": 0.02,
    "social": 0.02,
    "productivity": 0.03,
    "unknown": 0.04,
}

# P(client flags the app as sensitive | category).
_SENSITIVE_RATE: Final[dict[str, float]] = {
    "banking": 0.92,
    "payment": 0.88,
    "password_manager": 0.97,
    "health": 0.72,
    "messaging": 0.10,
    "social": 0.06,
    "media": 0.03,
    "productivity": 0.05,
    "system": 0.08,
    "unknown": 0.05,
}

#: Proportion of labels flipped after generation. Sets the Bayes error floor.
LABEL_NOISE_RATE: Final = 0.04

#: Proportion of critical-category contexts that are actually benign (a bank
#: app sitting on its login screen with nothing sensitive displayed).
BENIGN_CRITICAL_RATE: Final = 0.18

#: Proportion of non-critical contexts that actually contain sensitive content
#: (card details photographed into a chat, a health result forwarded by email).
HIDDEN_SENSITIVE_RATE: Final = 0.07


@dataclass
class ContextRecord:
    """A generated device context, duck-typed to match ``ContextSnapshot``."""

    foreground_app: str
    foreground_app_category: str
    is_sensitive_app: bool
    is_flag_secure_active: bool
    platform: str
    accessibility_enabled: bool
    accessibility_gesture_capable: bool
    screen_share_permission: bool
    microphone_permission: bool
    remote_control_permission: bool
    is_screen_sharing: bool
    battery_percent: int
    is_charging: bool
    network_type: str

    #: Ground truth available only in simulation.
    latent_sensitivity: float = 0.0
    is_benign_critical: bool = False
    is_hidden_sensitive: bool = False

    #: How involved the task the helpee is stuck on actually is. Drives which
    #: assistance mode genuinely resolves it. Partially observable through the
    #: app category and the sharing state.
    task_complexity: float = 0.5

    #: How much this helpee prefers to act for themselves. Partially observable
    #: through relationship history: someone on their fortieth session with the
    #: same helper has usually settled into doing more themselves.
    helpee_autonomy: float = 0.5


@dataclass
class RiskDataset:
    """Generated contexts with risk labels and simulation ground truth."""

    contexts: list[ContextRecord]
    labels: np.ndarray  # 1 = elevated risk (restrict), 0 = safe
    true_probabilities: np.ndarray  # P(risk) before label noise
    app_profiles: dict[str, dict[str, float]]
    histories: list[dict[str, float]]

    @property
    def bayes_accuracy(self) -> float:
        """Best achievable accuracy given the injected label noise.

        A perfect model predicts ``round(p)``; noise flips a fixed fraction of
        labels regardless. Reporting this alongside model accuracy is what makes
        the model number interpretable.
        """
        optimal = np.maximum(self.true_probabilities, 1.0 - self.true_probabilities)
        clean = float(np.mean(optimal))
        return clean * (1 - LABEL_NOISE_RATE) + (1 - clean) * LABEL_NOISE_RATE


@dataclass
class BanditLogDataset:
    """Logged bandit feedback with recorded propensities."""

    contexts: list[ContextRecord]
    features: np.ndarray
    actions: np.ndarray  # index into ACTIONS
    propensities: np.ndarray  # P(action | context) under the logging policy
    rewards: np.ndarray
    admissible: np.ndarray  # (n, |A|) boolean safety mask
    reward_table: np.ndarray  # (n, |A|) full counterfactual rewards


@dataclass
class SequenceDataset:
    """Ordered assistance-action sequences, one per session."""

    sequences: list[list[str]]
    user_ids: list[str]


@dataclass
class SecurityDataset:
    """Behavioural feature vectors with injected attack scenarios."""

    features: np.ndarray
    labels: np.ndarray  # 1 = anomalous
    scenario: list[str]
    feature_names: list[str]


# ----------------------------------------------------------------------
# Risk
# ----------------------------------------------------------------------


def _sample_category(generator: np.random.Generator, n: int) -> np.ndarray:
    categories = np.array(list(_CATEGORY_WEIGHTS))
    weights = np.array(list(_CATEGORY_WEIGHTS.values()))
    return generator.choice(categories, size=n, p=weights / weights.sum())


def generate_risk_dataset(n_samples: int = 12000, *, label: str = "risk") -> RiskDataset:
    """Generate contexts and risk labels via the documented process.

    Args:
        n_samples: Number of contexts.
        label: Seed label; use different labels for train and held-out sets so
            the two are drawn from independent streams of the same process.

    Returns:
        A :class:`RiskDataset`.
    """
    generator = rng(label)
    categories = _sample_category(generator, n_samples)

    # Histories are drawn first so that latent helpee autonomy can be
    # correlated with them. Generating the two independently would make
    # autonomy unlearnable from any observable feature, which would turn the
    # bandit problem into pure noise and any "learning" into overfitting.
    histories = _build_histories(generator, n_samples)

    contexts: list[ContextRecord] = []
    latent = np.zeros(n_samples)

    # How involved a task in each app category typically is. Settings and
    # productivity apps produce the multi-step problems that genuinely need
    # hands-on help; media and social apps rarely do.
    complexity_by_category = {
        "system": 0.78,
        "productivity": 0.68,
        "banking": 0.62,
        "payment": 0.60,
        "health": 0.55,
        "password_manager": 0.58,
        "messaging": 0.42,
        "unknown": 0.45,
        "social": 0.34,
        "media": 0.26,
    }

    for i, category in enumerate(categories):
        is_critical = category in CRITICAL_CATEGORIES

        # The two populations where a rule based on category alone is wrong.
        benign_critical = bool(
            is_critical and generator.random() < BENIGN_CRITICAL_RATE
        )
        hidden_sensitive = bool(
            not is_critical and generator.random() < HIDDEN_SENSITIVE_RATE
        )

        flag_secure = generator.random() < _FLAG_SECURE_RATE[category]
        sensitive = generator.random() < _SENSITIVE_RATE[category]

        # A benign critical app is on a splash or login screen: the OS flag may
        # still be set, but no personal content is rendered.
        if benign_critical:
            sensitive = generator.random() < 0.25
        # Hidden sensitivity is invisible to the category and usually to the
        # OS flag too — which is precisely why rules miss it.
        if hidden_sensitive:
            sensitive = generator.random() < 0.55
            flag_secure = flag_secure or generator.random() < 0.10

        accessibility = generator.random() < 0.55
        gesture_capable = accessibility and generator.random() < 0.80

        # Latent sensitivity. A weighted sum on the log-odds scale with two
        # interaction terms the rule engine cannot express.
        score = -2.6
        score += 2.1 * float(flag_secure)
        score += 1.6 * float(sensitive)
        score += 1.9 * float(is_critical)
        score += 2.4 * float(hidden_sensitive)
        score -= 2.0 * float(benign_critical)
        # Interaction: a critical app that is *also* actively protected is far
        # riskier than the sum of the two signals.
        score += 1.3 * float(is_critical and flag_secure)
        # Interaction: gesture capability raises the stakes of a wrong call,
        # because a mistake becomes a tap rather than a drawn circle.
        score += 0.7 * float(gesture_capable and (sensitive or flag_secure))
        score += generator.normal(0.0, 0.35)

        latent[i] = score

        task_complexity = float(
            np.clip(
                complexity_by_category[category] + generator.normal(0.0, 0.16),
                0.0,
                1.0,
            )
        )
        # Experience with this helper predicts autonomy, with real spread —
        # some people stay dependent and some are independent from session one.
        experience = min(1.0, histories[i]["prior_sessions"] / 30.0)
        helpee_autonomy = float(
            np.clip(0.25 + 0.5 * experience + generator.normal(0.0, 0.18), 0.0, 1.0)
        )

        contexts.append(
            ContextRecord(
                foreground_app=f"com.example.{category}{generator.integers(1, 9)}",
                foreground_app_category=str(category),
                is_sensitive_app=bool(sensitive),
                is_flag_secure_active=bool(flag_secure),
                platform=str(
                    generator.choice(
                        ["android", "ios", "unknown"], p=[0.80, 0.17, 0.03]
                    )
                ),
                accessibility_enabled=bool(accessibility),
                accessibility_gesture_capable=bool(gesture_capable),
                screen_share_permission=bool(generator.random() < 0.85),
                microphone_permission=bool(generator.random() < 0.90),
                remote_control_permission=bool(gesture_capable and generator.random() < 0.6),
                is_screen_sharing=bool(generator.random() < 0.75),
                battery_percent=int(generator.integers(3, 100)),
                is_charging=bool(generator.random() < 0.35),
                network_type=str(
                    generator.choice(
                        ["wifi", "cellular", "none", "unknown"],
                        p=[0.68, 0.27, 0.02, 0.03],
                    )
                ),
                latent_sensitivity=float(score),
                is_benign_critical=benign_critical,
                is_hidden_sensitive=hidden_sensitive,
                task_complexity=task_complexity,
                helpee_autonomy=helpee_autonomy,
            )
        )

    probabilities = 1.0 / (1.0 + np.exp(-latent))
    labels = (generator.random(n_samples) < probabilities).astype(int)

    # Symmetric label noise, applied last so it is independent of the features.
    flip = generator.random(n_samples) < LABEL_NOISE_RATE
    labels[flip] = 1 - labels[flip]

    app_profiles = _build_app_profiles(contexts, labels)

    return RiskDataset(
        contexts=contexts,
        labels=labels,
        true_probabilities=probabilities,
        app_profiles=app_profiles,
        histories=histories,
    )


def _build_app_profiles(
    contexts: list[ContextRecord], labels: np.ndarray
) -> dict[str, dict[str, float]]:
    """Aggregate per-app rates, mirroring ``mv_app_risk_profile``.

    The k>=5 floor matches the materialised view's ``HAVING`` clause, so the
    cold-start behaviour seen in training is the behaviour production has.
    """
    buckets: dict[str, list[tuple[int, int]]] = {}
    for context, label in zip(contexts, labels):
        buckets.setdefault(context.foreground_app, []).append(
            (int(label), int(context.is_sensitive_app))
        )

    profiles: dict[str, dict[str, float]] = {}
    for app, rows in buckets.items():
        if len(rows) < 5:
            continue
        risk = float(np.mean([r[0] for r in rows]))
        sensitive = float(np.mean([r[1] for r in rows]))
        profiles[app] = {
            "high_risk_rate": risk,
            "sensitive_rate": sensitive,
            "observation_count": float(len(rows)),
        }
    return profiles


def _build_histories(
    generator: np.random.Generator, n_samples: int
) -> list[dict[str, float]]:
    """Per-relationship history aggregates, mirroring the user profile view."""
    # Session counts are heavily skewed: most helpee-helper pairs have a handful
    # of sessions, a few have hundreds.
    prior_sessions = generator.gamma(shape=1.4, scale=6.0, size=n_samples)
    trust_age = prior_sessions * generator.uniform(2.0, 14.0, size=n_samples)
    escalation_rate = generator.beta(1.5, 8.0, size=n_samples)
    return [
        {
            "prior_sessions": float(prior_sessions[i]),
            "trust_age_days": float(trust_age[i]),
            "escalation_rate": float(escalation_rate[i]),
        }
        for i in range(n_samples)
    ]


# ----------------------------------------------------------------------
# Bandit
# ----------------------------------------------------------------------


def _reward_table(
    contexts: list[ContextRecord], risk_probabilities: np.ndarray
) -> np.ndarray:
    """Ground-truth expected reward of each action in each context.

    Reward is **not monotonic in privilege**, and that is the modelling decision
    that makes this a real contextual bandit problem rather than a dressed-up
    ranking task.

    An earlier version of this table made higher privilege strictly better
    whenever it was admissible. Under that reward the optimal policy is "take
    the safety envelope's ceiling" — which is exactly what the rule engine
    already does, so the rule baseline achieved near-zero regret and there was
    nothing for a learner to contribute. The result was an artefact of the
    reward model, not a finding about rules.

    It was also wrong about the domain. Remote-controlling someone's phone when
    a spoken instruction would have worked is not a better outcome: it is worse.
    The person learns nothing, their sense of competence erodes, and the
    literature on assistive technology for older adults is consistent that
    over-assistance drives abandonment. So reward peaks at a *context-dependent*
    mode::

        optimal(x) ≈ f(task_complexity, helpee_autonomy, gesture_capability)

    A complex task for a dependent user genuinely needs hands-on control; a
    simple task for an independent one is best served by voice. Both latents are
    partially observable — complexity through the app category, autonomy through
    relationship history — so the correct action is learnable from features but
    not deducible from any fixed rule, which is precisely the regime where a
    contextual policy earns its place.

    Known in closed form only because this is a simulator; that is what makes
    off-policy estimates checkable against a true value.
    """
    n = len(contexts)
    table = np.zeros((n, len(ACTIONS)))

    # Exposure cost multiplier of each mode when the context is risky.
    exposure = np.array([0.00, 0.10, 0.30, 0.45, 1.00])

    for i, context in enumerate(contexts):
        risk = float(risk_probabilities[i])
        gesture = context.accessibility_gesture_capable

        # Where the ideal amount of help sits on the 0-4 privilege scale.
        # Complexity pushes up, autonomy pushes down.
        ideal = 1.0 + 3.0 * context.task_complexity - 1.6 * context.helpee_autonomy
        ideal = float(np.clip(ideal, 0.0, 4.0))

        for j, action in enumerate(ACTIONS):
            distance = abs(j - ideal)
            # Under-helping fails to solve the problem; over-helping solves it
            # while undermining the person. Under-helping is penalised somewhat
            # harder, because an unsolved problem is the reason they called.
            penalty = 0.26 * distance if j >= ideal else 0.34 * distance
            value = 0.95 - penalty
            value -= 1.25 * risk * exposure[j]
            # A mode requiring gestures is useless without the capability.
            if action == "tap" and not gesture:
                value -= 0.55
            table[i, j] = value

    # Squash to [0, 1]: the reward column and its CHECK constraint on
    # ml_decision_log both require a unit-interval reward.
    return 1.0 / (1.0 + np.exp(-3.0 * table))


def _admissible_mask(contexts: list[ContextRecord], labels: np.ndarray) -> np.ndarray:
    """The safety envelope's admissible action set per context.

    Mirrors :class:`ml.risk.safety.SafetyEnvelope` exactly. The bandit never
    sees an inadmissible action, in training or in evaluation, so a regret
    curve cannot be flattered by counting rewards from actions the deployed
    system would refuse to take.
    """
    from ml.config import ACTION_INDEX

    mask = np.ones((len(contexts), len(ACTIONS)), dtype=bool)
    for i, context in enumerate(contexts):
        if labels[i] == 1 or context.is_flag_secure_active:
            for action in ("pointer", "drawing", "tap"):
                mask[i, ACTION_INDEX[action]] = False
        if not context.accessibility_gesture_capable:
            mask[i, ACTION_INDEX["tap"]] = False
    return mask


def generate_bandit_logs(
    n_samples: int = 8000,
    *,
    epsilon: float = 0.25,
    label: str = "bandit",
) -> BanditLogDataset:
    """Generate logged feedback under a known epsilon-greedy logging policy.

    The logging policy is a deliberately mediocre rule-based one: it picks the
    least-privilege admissible mode most of the time and explores uniformly
    otherwise. Two properties make the log usable for off-policy evaluation:

    * **Recorded propensities.** ``P(action | context)`` is written down at
      decision time, because it cannot be recovered later.
    * **Full support.** Every admissible action keeps probability at least
      ``epsilon / |admissible|``, so no counterfactual is unidentifiable.
      Importance weights stay bounded, which is what keeps IPS variance finite.

    Only the reward of the *taken* action is revealed to any estimator; the
    full table is retained solely to compute the true policy value that the
    estimators are scored against.
    """
    generator = rng(label)
    risk = generate_risk_dataset(n_samples, label=f"{label}-contexts")
    contexts = risk.contexts

    from ml.features import extract, to_matrix

    features = to_matrix(
        extract(
            context,
            app_profile=risk.app_profiles.get(context.foreground_app),
            history=history,
        )
        for context, history in zip(contexts, risk.histories)
    )

    admissible = _admissible_mask(contexts, risk.labels)
    rewards_full = _reward_table(contexts, risk.true_probabilities)

    n_actions = len(ACTIONS)
    actions = np.zeros(n_samples, dtype=int)
    propensities = np.zeros(n_samples)
    observed = np.zeros(n_samples)

    for i in range(n_samples):
        allowed = np.flatnonzero(admissible[i])
        # Least-privilege greedy choice: the lowest-index admissible action.
        greedy = allowed[0]

        probabilities = np.zeros(n_actions)
        probabilities[allowed] = epsilon / len(allowed)
        probabilities[greedy] += 1.0 - epsilon

        chosen = generator.choice(n_actions, p=probabilities)
        actions[i] = chosen
        propensities[i] = probabilities[chosen]
        # Bernoulli reward around the expected value: a real system observes a
        # noisy outcome, not the expectation.
        observed[i] = float(generator.random() < rewards_full[i, chosen])

    return BanditLogDataset(
        contexts=contexts,
        features=features,
        actions=actions,
        propensities=propensities,
        rewards=observed,
        admissible=admissible,
        reward_table=rewards_full,
    )


# ----------------------------------------------------------------------
# Sequences
# ----------------------------------------------------------------------

#: Assistance actions a helper takes during a session.
SEQUENCE_ACTIONS: Final = (
    "voice",
    "screen_share",
    "pointer",
    "drawing",
    "chat",
    "remote_control",
    "end",
)

# A hand-specified first-order transition matrix representing plausible help
# workflows: a session opens with voice, escalates through pointing and drawing
# only if those fail, and reaches remote control rarely.
_TRANSITIONS: Final[dict[str, dict[str, float]]] = {
    "<start>": {"voice": 0.72, "screen_share": 0.20, "chat": 0.08},
    "voice": {"screen_share": 0.55, "pointer": 0.12, "chat": 0.13, "end": 0.20},
    "screen_share": {"pointer": 0.40, "drawing": 0.26, "voice": 0.14, "remote_control": 0.08, "end": 0.12},
    "pointer": {"drawing": 0.45, "voice": 0.18, "remote_control": 0.15, "end": 0.22},
    "drawing": {"remote_control": 0.22, "voice": 0.20, "pointer": 0.16, "end": 0.42},
    "chat": {"voice": 0.46, "screen_share": 0.28, "end": 0.26},
    "remote_control": {"end": 0.62, "voice": 0.22, "drawing": 0.16},
}


def generate_sequence_dataset(
    n_sessions: int = 4000,
    n_users: int = 260,
    *,
    label: str = "sequence",
) -> SequenceDataset:
    """Generate per-session assistance-action sequences.

    Each user is given a persistent bias toward one action, so a personalised
    model has something to learn that a population model cannot capture. This
    is what separates a real recommender evaluation from one where the global
    popularity baseline is already optimal.
    """
    generator = rng(label)
    user_ids = [f"user-{i:04d}" for i in range(n_users)]
    user_bias = {
        user: str(generator.choice(SEQUENCE_ACTIONS[:-1])) for user in user_ids
    }
    bias_strength = 0.30

    sequences: list[list[str]] = []
    owners: list[str] = []

    for _ in range(n_sessions):
        user = str(generator.choice(user_ids))
        favourite = user_bias[user]
        state = "<start>"
        sequence: list[str] = []

        for _ in range(12):  # hard cap; sessions terminate on "end"
            options = _TRANSITIONS[state]
            names = list(options)
            weights = np.array([options[name] for name in names], dtype=float)

            if favourite in names:
                weights[names.index(favourite)] += bias_strength
            weights = weights / weights.sum()

            state = str(generator.choice(names, p=weights))
            if state == "end":
                break
            sequence.append(state)

        if len(sequence) >= 2:
            sequences.append(sequence)
            owners.append(user)

    return SequenceDataset(sequences=sequences, user_ids=owners)


# ----------------------------------------------------------------------
# Security anomalies
# ----------------------------------------------------------------------

#: Proportion of injected attacks that are blended toward normal behaviour.
#: Without stealth cases the classes separate perfectly and the reported
#: ROC-AUC measures the simulator rather than the detector.
STEALTH_FRACTION: Final = 0.55

SECURITY_FEATURE_NAMES: Final = [
    "pairing_attempts_1h",
    "distinct_targets_1h",
    "failed_code_attempts",
    "escalation_requests_per_session",
    "escalation_request_latency_s",
    "session_hour_sin",
    "session_hour_cos",
    "helper_account_age_days_log",
    "session_duration_s_log",
    "control_requests_per_minute",
    "distinct_apps_touched",
    "revocation_count_30d",
]


def generate_security_dataset(
    n_normal: int = 6000,
    n_attack: int = 320,
    *,
    label: str = "security",
) -> SecurityDataset:
    """Generate behavioural vectors with three injected attack scenarios.

    The attacks are modelled on documented elder-fraud patterns rather than
    invented:

    * **Pairing spam** — one actor sending trust requests to many strangers in
      a short window, the digital analogue of cold-call fraud.
    * **Escalation probing** — a helper who repeatedly requests control
      immediately on connecting, testing whether the person will eventually
      tap Allow out of confusion or fatigue.
    * **Coercion** — an unusually long session, at an unusual hour, from a very
      new account, touching many apps: the signature of a scammer walking
      someone through a transfer.

    The base rate is deliberately low (~5%), because an anomaly detector
    evaluated on balanced classes reports a precision it will never achieve
    against real traffic.

    Stealth
    -------
    A proportion of attacks (``stealth_fraction``) are generated as a blend
    between the attack profile and the normal profile, controlled by a per-case
    blending weight. Without this the injected attacks are trivially separable
    and the detector reports an ROC-AUC of 1.0 — a number that says the
    simulator is easy, not that the detector is good.

    Blending is also the realistic model. An attacker who has been caught once
    adapts: they space pairing requests out, they wait before asking for
    control, they operate during the day. The interesting and dangerous cases
    are the ones that partially resemble legitimate use, and a detector should
    be evaluated on how far into that overlap it can reach.
    """
    generator = rng(label)
    rows: list[list[float]] = []
    labels: list[int] = []
    scenarios: list[str] = []

    def normal_profile(hour: float) -> list[float]:
        """A draw from the legitimate-behaviour distribution."""
        return [
            float(generator.poisson(0.35)),
            float(generator.poisson(0.25)),
            float(generator.poisson(0.30)),
            float(generator.poisson(0.45)),
            float(np.abs(generator.normal(220.0, 90.0))),
            float(np.sin(2 * np.pi * hour / 24)),
            float(np.cos(2 * np.pi * hour / 24)),
            float(np.log1p(np.abs(generator.normal(420.0, 260.0)))),
            float(np.log1p(np.abs(generator.normal(560.0, 300.0)))),
            float(np.abs(generator.normal(0.7, 0.45))),
            float(generator.poisson(2.4)),
            float(generator.poisson(0.12)),
        ]

    def blended(attack: list[float], hour: float) -> list[float]:
        """Move an attack vector partway toward a normal draw.

        ``weight`` is the fraction of the attack signal retained. Drawn from a
        Beta distribution skewed toward the attack end, so most attacks stay
        recognisable and a minority are genuinely subtle — which is the shape
        that produces a realistic precision/recall curve rather than a step
        function.
        """
        if generator.random() >= STEALTH_FRACTION:
            return attack
        weight = float(generator.beta(2.0, 1.6))
        baseline = normal_profile(hour)
        return [
            weight * a + (1.0 - weight) * b for a, b in zip(attack, baseline)
        ]

    for _ in range(n_normal):
        hour = float(generator.normal(14.0, 3.4)) % 24
        rows.append(normal_profile(hour))
        labels.append(0)
        scenarios.append("normal")

    per_scenario = n_attack // 3
    remainder = n_attack - 2 * per_scenario

    for _ in range(per_scenario):  # pairing spam
        hour = float(generator.uniform(0, 24))
        attack = [
                float(generator.poisson(18.0)),
                float(generator.poisson(14.0)),
                float(generator.poisson(9.0)),
                float(generator.poisson(0.4)),
                float(np.abs(generator.normal(60.0, 40.0))),
                float(np.sin(2 * np.pi * hour / 24)),
                float(np.cos(2 * np.pi * hour / 24)),
                float(np.log1p(np.abs(generator.normal(3.0, 2.0)))),
                float(np.log1p(np.abs(generator.normal(90.0, 60.0)))),
                float(np.abs(generator.normal(0.5, 0.3))),
                float(generator.poisson(1.0)),
                float(generator.poisson(2.5)),
        ]
        rows.append(blended(attack, hour))
        labels.append(1)
        scenarios.append("pairing_spam")

    for _ in range(per_scenario):  # escalation probing
        hour = float(generator.normal(15.0, 4.0)) % 24
        attack = [
                float(generator.poisson(0.6)),
                float(generator.poisson(0.4)),
                float(generator.poisson(0.5)),
                float(generator.poisson(7.5)),
                float(np.abs(generator.normal(12.0, 8.0))),
                float(np.sin(2 * np.pi * hour / 24)),
                float(np.cos(2 * np.pi * hour / 24)),
                float(np.log1p(np.abs(generator.normal(25.0, 18.0)))),
                float(np.log1p(np.abs(generator.normal(300.0, 150.0)))),
                float(np.abs(generator.normal(4.2, 1.4))),
                float(generator.poisson(1.6)),
                float(generator.poisson(0.9)),
        ]
        rows.append(blended(attack, hour))
        labels.append(1)
        scenarios.append("escalation_probing")

    for _ in range(remainder):  # coercion
        hour = float(generator.normal(2.5, 2.0)) % 24
        attack = [
                float(generator.poisson(0.4)),
                float(generator.poisson(0.3)),
                float(generator.poisson(0.2)),
                float(generator.poisson(2.2)),
                float(np.abs(generator.normal(400.0, 150.0))),
                float(np.sin(2 * np.pi * hour / 24)),
                float(np.cos(2 * np.pi * hour / 24)),
                float(np.log1p(np.abs(generator.normal(6.0, 4.0)))),
                float(np.log1p(np.abs(generator.normal(4200.0, 900.0)))),
                float(np.abs(generator.normal(1.9, 0.6))),
                float(generator.poisson(9.5)),
                float(generator.poisson(0.3)),
        ]
        rows.append(blended(attack, hour))
        labels.append(1)
        scenarios.append("coercion")

    features = np.array(rows, dtype=np.float64)
    order = generator.permutation(len(labels))

    return SecurityDataset(
        features=features[order],
        labels=np.array(labels)[order],
        scenario=[scenarios[i] for i in order],
        feature_names=list(SECURITY_FEATURE_NAMES),
    )
