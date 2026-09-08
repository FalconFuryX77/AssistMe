"""Safety invariants for the machine-learning decision path.

These are the tests that make a learned policy defensible on a path that grants
a third party control of an elderly person's phone. They assert *absolute*
properties, not statistical ones: "the model is usually right" is not a safety
argument, and no threshold on accuracy would make one.

Every test here should be readable by someone who does not write Python, because
the property being asserted is a product commitment, not an implementation
detail.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from ml.config import ACTION_INDEX, ACTIONS, COST_FALSE_RISKY, COST_FALSE_SAFE
from ml.features import FEATURE_NAMES, extract, to_matrix
from ml.risk.model import RiskClassifier, cost_optimal_threshold
from ml.risk.safety import SafetyEnvelope


def context(**overrides) -> SimpleNamespace:
    """A device context with permissive defaults, overridden per test."""
    base = dict(
        foreground_app="com.example.notes",
        foreground_app_category="productivity",
        is_sensitive_app=False,
        is_flag_secure_active=False,
        platform="android",
        accessibility_enabled=True,
        accessibility_gesture_capable=True,
        screen_share_permission=True,
        microphone_permission=True,
        remote_control_permission=True,
        is_screen_sharing=True,
        battery_percent=80,
        is_charging=False,
        network_type="wifi",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# The envelope
# ---------------------------------------------------------------------------


class TestSafetyEnvelope:
    def test_flag_secure_caps_at_voice(self) -> None:
        """A protected screen leaves voice guidance and nothing more."""
        ceiling, risk, reasons = SafetyEnvelope.ceiling(
            context(is_flag_secure_active=True)
        )
        assert ceiling == "voice"
        assert risk == "high"
        assert reasons

    @pytest.mark.parametrize(
        "category", ["banking", "payment", "health", "password_manager"]
    )
    def test_critical_categories_cap_at_voice(self, category: str) -> None:
        ceiling, risk, _ = SafetyEnvelope.ceiling(
            context(foreground_app_category=category)
        )
        assert ceiling == "voice"
        assert risk == "high"

    def test_sensitive_app_caps_at_drawing(self) -> None:
        """A weaker signal restricts less: annotation stays, tapping does not."""
        ceiling, risk, _ = SafetyEnvelope.ceiling(context(is_sensitive_app=True))
        assert ceiling == "drawing"
        assert risk == "medium"

    def test_tap_requires_gesture_capability(self) -> None:
        ceiling, _, _ = SafetyEnvelope.ceiling(
            context(accessibility_gesture_capable=False)
        )
        assert ACTION_INDEX[ceiling] < ACTION_INDEX["tap"]

    def test_clamping_only_ever_lowers_privilege(self) -> None:
        """The central invariant: the envelope can restrict, never grant.

        Enumerated over every context/proposal pair rather than sampled,
        because the property is absolute.
        """
        contexts = [
            context(),
            context(is_flag_secure_active=True),
            context(is_sensitive_app=True),
            context(foreground_app_category="banking"),
            context(accessibility_gesture_capable=False),
            context(is_flag_secure_active=True, accessibility_gesture_capable=False),
            context(foreground_app_category="health", is_sensitive_app=True),
        ]
        for ctx in contexts:
            ceiling, _, _ = SafetyEnvelope.ceiling(ctx)
            for proposed in ACTIONS:
                decision = SafetyEnvelope.apply(ctx, proposed)
                assert ACTION_INDEX[decision.action] <= ACTION_INDEX[ceiling]
                assert ACTION_INDEX[decision.action] <= ACTION_INDEX[proposed]

    @pytest.mark.parametrize(
        "garbage", ["tap ", "TAP", "administrator", "", "'; DROP TABLE sessions;--"]
    )
    def test_unknown_mode_fails_closed(self, garbage: str) -> None:
        """An unrecognised mode must become the safest option, not pass through.

        This is the injection case: a compromised client sending an
        unrecognised capability string must not receive more than it should.
        """
        decision = SafetyEnvelope.apply(context(), garbage)
        assert decision.action == "restricted"

    def test_high_risk_never_admits_interaction(self) -> None:
        """No interactive mode is ever admissible at rule-assessed high risk."""
        for ctx in (
            context(is_flag_secure_active=True),
            context(foreground_app_category="banking"),
            context(foreground_app_category="password_manager"),
        ):
            admissible = SafetyEnvelope.admissible(ctx)
            assert "tap" not in admissible
            assert "drawing" not in admissible
            assert "pointer" not in admissible

    def test_restricted_is_always_admissible(self) -> None:
        """Every context has at least one legal action, so callers never see
        an empty action set."""
        for ctx in (
            context(),
            context(is_flag_secure_active=True),
            context(foreground_app_category="banking", accessibility_gesture_capable=False),
        ):
            assert SafetyEnvelope.admissible(ctx)

    def test_reasons_are_plain_language(self) -> None:
        """Justifications are shown to an elderly user verbatim, so they must
        not contain identifiers or jargon."""
        _, _, reasons = SafetyEnvelope.ceiling(context(is_flag_secure_active=True))
        assert reasons
        for reason in reasons:
            assert reason[0].isupper() and reason.endswith(".")
            for jargon in ("FLAG_SECURE", "null", "None", "accessibility_gesture"):
                assert jargon not in reason


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------


class TestFeatures:
    def test_vector_order_is_stable(self) -> None:
        """Column order is the model's input contract."""
        vector = extract(context())
        assert list(vector.as_dict()) == list(FEATURE_NAMES)
        assert vector.as_array().shape == (len(FEATURE_NAMES),)

    def test_all_features_are_finite(self) -> None:
        """No NaN or infinity may reach a model, whatever the client sends."""
        awkward = [
            context(),
            context(battery_percent=None, network_type=None, platform=None),
            context(foreground_app_category=None, foreground_app=None),
            context(battery_percent=-5),
            context(battery_percent=500),
        ]
        matrix = to_matrix(extract(c) for c in awkward)
        assert np.isfinite(matrix).all()

    def test_unknown_category_falls_into_its_own_bucket(self) -> None:
        vector = extract(context(foreground_app_category="something-new"))
        assert vector.category_unknown == 1.0
        assert vector.is_critical_category == 0.0

    def test_battery_is_clamped_to_a_percentage(self) -> None:
        assert extract(context(battery_percent=500)).battery_normalised == 1.0
        assert extract(context(battery_percent=-10)).battery_normalised == 0.0

    def test_cold_start_app_profile_is_handled(self) -> None:
        """An app absent from the population view must not break extraction."""
        vector = extract(context(), app_profile=None)
        assert vector.app_high_risk_rate == 0.0
        assert vector.app_observation_weight == 0.0

    def test_extraction_is_deterministic(self) -> None:
        ctx = context()
        assert np.array_equal(extract(ctx).as_array(), extract(ctx).as_array())


# ---------------------------------------------------------------------------
# Cost-sensitive decisions
# ---------------------------------------------------------------------------


class TestCostSensitiveThreshold:
    def test_threshold_matches_the_declared_cost_ratio(self) -> None:
        expected = COST_FALSE_RISKY / (COST_FALSE_RISKY + COST_FALSE_SAFE)
        assert cost_optimal_threshold() == pytest.approx(expected)

    def test_threshold_is_well_below_a_half(self) -> None:
        """Protecting someone must be cheaper than inconveniencing them."""
        assert cost_optimal_threshold() < 0.2

    def test_symmetric_costs_recover_one_half(self) -> None:
        assert cost_optimal_threshold(1.0, 1.0) == pytest.approx(0.5)

    def test_higher_safety_cost_lowers_the_threshold(self) -> None:
        assert cost_optimal_threshold(100.0, 1.0) < cost_optimal_threshold(10.0, 1.0)

    def test_risk_level_and_binary_decision_agree(self) -> None:
        """A row cannot be 'low' risk and simultaneously flagged risky."""
        classifier = RiskClassifier()
        for probability in np.linspace(0.0, 1.0, 101):
            prediction = classifier.interpret(float(probability))
            if prediction.risk_level == "low":
                assert not prediction.is_risky
            else:
                assert prediction.is_risky

    def test_abstention_band_brackets_the_threshold(self) -> None:
        classifier = RiskClassifier()
        low, high = classifier.abstention_band()
        assert low <= classifier.threshold <= high
        assert classifier.interpret(classifier.threshold).abstained
        assert not classifier.interpret(0.99).abstained
        assert not classifier.interpret(0.0).abstained

    def test_confidence_is_zero_at_the_boundary(self) -> None:
        classifier = RiskClassifier()
        assert classifier.interpret(classifier.threshold).confidence == pytest.approx(
            0.0, abs=1e-9
        )
        assert classifier.interpret(1.0).confidence > 0.9


# ---------------------------------------------------------------------------
# Bandit safety
# ---------------------------------------------------------------------------


class TestBanditSafety:
    def _mask(self, ctx) -> np.ndarray:
        allowed = set(SafetyEnvelope.admissible(ctx))
        return np.array([action in allowed for action in ACTIONS])

    @pytest.mark.parametrize(
        "policy_name", ["linucb", "thompson", "epsilon_greedy", "random"]
    )
    def test_no_probability_mass_outside_the_admissible_set(
        self, policy_name: str
    ) -> None:
        """A policy must never be *able* to choose a forbidden action.

        Filtering afterwards is not equivalent: a policy that assigns mass to
        an inadmissible action will eventually take it if the filter is ever
        bypassed or misordered.
        """
        from ml.bandit.policies import (
            EpsilonGreedyPolicy,
            LinUCBPolicy,
            RandomPolicy,
            ThompsonSamplingPolicy,
        )

        dimension = len(FEATURE_NAMES)
        policies = {
            "linucb": LinUCBPolicy(dimension),
            "thompson": ThompsonSamplingPolicy(dimension, n_probability_samples=16),
            "epsilon_greedy": EpsilonGreedyPolicy(dimension),
            "random": RandomPolicy(),
        }
        policy = policies[policy_name]

        for ctx in (
            context(),
            context(is_flag_secure_active=True),
            context(foreground_app_category="banking"),
            context(accessibility_gesture_capable=False),
        ):
            mask = self._mask(ctx)
            features = extract(ctx).as_array()
            probabilities = policy.probabilities(features, mask)

            assert probabilities[~mask].sum() == pytest.approx(0.0)
            assert probabilities.sum() == pytest.approx(1.0)
            assert (probabilities[mask] > 0).all(), (
                "an admissible action received zero probability, which makes "
                "its off-policy estimate undefined"
            )

    def test_selection_stays_inside_the_admissible_set(self) -> None:
        from ml.bandit.policies import ThompsonSamplingPolicy

        policy = ThompsonSamplingPolicy(
            len(FEATURE_NAMES), n_probability_samples=16
        )
        ctx = context(is_flag_secure_active=True)
        mask = self._mask(ctx)
        features = extract(ctx).as_array()

        for _ in range(50):
            decision = policy.select(features, mask)
            assert mask[decision.action_index]
            assert decision.propensity > 0

    def test_learning_never_widens_the_action_set(self) -> None:
        """Reward on a permissive context must not unlock actions elsewhere."""
        from ml.bandit.policies import LinUCBPolicy

        policy = LinUCBPolicy(len(FEATURE_NAMES))
        permissive = extract(context()).as_array()
        for _ in range(200):
            policy.update(permissive, ACTION_INDEX["tap"], 1.0)

        restricted_context = context(is_flag_secure_active=True)
        mask = self._mask(restricted_context)
        probabilities = policy.probabilities(
            extract(restricted_context).as_array(), mask
        )
        assert probabilities[ACTION_INDEX["tap"]] == 0.0


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


class TestReproducibility:
    def test_seeds_are_independent_per_label(self) -> None:
        """Components must not share a random stream.

        Two components drawing from the same seed consume correlated draws,
        which silently couples (for instance) the dataset generator to the
        bandit's exploration and invalidates any regret measurement.
        """
        from ml.config import seed_for

        labels = ["risk", "bandit", "sequence", "anomaly", "risk-train", "risk-test"]
        seeds = [seed_for(label) for label in labels]
        assert len(set(seeds)) == len(seeds)

    def test_generators_are_deterministic(self) -> None:
        from ml.datasets.generators import generate_risk_dataset

        first = generate_risk_dataset(200, label="determinism-check")
        second = generate_risk_dataset(200, label="determinism-check")
        assert np.array_equal(first.labels, second.labels)
        assert np.allclose(first.true_probabilities, second.true_probabilities)

    def test_different_labels_give_different_data(self) -> None:
        from ml.datasets.generators import generate_risk_dataset

        train = generate_risk_dataset(400, label="split-a")
        test = generate_risk_dataset(400, label="split-b")
        assert not np.array_equal(train.labels, test.labels)
