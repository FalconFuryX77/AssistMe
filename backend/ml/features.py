"""Feature extraction: the single contract between live context and every model.

Why one module
--------------
Training-serving skew is the most common way a model that evaluates well fails
in production: the training pipeline computes a feature one way and the request
path computes it another, so the model sees a distribution it never learned on.
The usual cause is two implementations of the same idea in two files.

There is one implementation here. :func:`extract` is called by the training
pipeline over historical ``context_events`` rows and by the inference service
over a live ``ContextSnapshot``, and both go through :class:`FeatureVector`,
whose field order *is* the model's input order. Adding a feature in one place
without the other is a type error rather than a silent distribution shift.

Design choices
--------------
**Ordered, named, and fixed.** :data:`FEATURE_NAMES` is the canonical order.
The vector is built by iterating it, so a reordered dataclass cannot silently
permute the columns a fitted model expects.

**No learned encoders on the hot path.** Categorical values are encoded by
fixed lookup, not by a fitted ``OneHotEncoder``. An encoder fitted on training
data is another artefact to version and another way for serving to diverge; a
fixed vocabulary with an explicit "unknown" bucket is deterministic, needs no
artefact, and handles the app-nobody-has-seen-before case by construction —
which matters, because that is the common case on a device fleet.

**Population priors as features.** ``app_high_risk_rate`` and
``app_sensitive_rate`` come from ``mv_app_risk_profile``. This is where the
database's materialised views feed the model directly: a per-app empirical rate
computed over the whole population is exactly the informative prior a
cold-start user lacks, and it is far cheaper to read from a refreshed view than
to aggregate per request.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, Final, Iterable, Mapping

import numpy as np

__all__ = [
    "APP_CATEGORIES",
    "FEATURE_NAMES",
    "FeatureVector",
    "extract",
    "to_matrix",
]

#: Application categories the client reports. ``unknown`` is a real member, not
#: a failure case: most installed apps are uncategorised, and the model must
#: learn what an uncategorised app implies rather than treating it as missing.
APP_CATEGORIES: Final = (
    "banking",
    "payment",
    "health",
    "password_manager",
    "messaging",
    "social",
    "productivity",
    "system",
    "media",
    "unknown",
)

#: Categories whose contents are financially or medically sensitive by nature.
#: Used both as a feature and as the rule engine's hard trigger.
CRITICAL_CATEGORIES: Final = frozenset(
    {"banking", "payment", "health", "password_manager"}
)

PLATFORMS: Final = ("android", "ios", "web", "unknown")
NETWORK_TYPES: Final = ("wifi", "cellular", "ethernet", "none", "unknown")


@dataclass(frozen=True)
class FeatureVector:
    """One model input. Field order defines column order; see module docstring."""

    # --- protection signals (the strongest predictors) -------------------
    is_flag_secure_active: float
    is_sensitive_app: float
    is_critical_category: float

    # --- application identity --------------------------------------------
    category_banking: float
    category_payment: float
    category_health: float
    category_password_manager: float
    category_messaging: float
    category_social: float
    category_productivity: float
    category_system: float
    category_media: float
    category_unknown: float

    # --- population priors from mv_app_risk_profile ----------------------
    app_high_risk_rate: float
    app_sensitive_rate: float
    app_observation_weight: float

    # --- capability state -------------------------------------------------
    accessibility_enabled: float
    accessibility_gesture_capable: float
    screen_share_permission: float
    microphone_permission: float
    remote_control_permission: float
    is_screen_sharing: float

    # --- platform ----------------------------------------------------------
    platform_android: float
    platform_ios: float
    platform_web: float
    platform_unknown: float

    # --- device and network conditions ------------------------------------
    battery_normalised: float
    battery_is_low: float
    is_charging: float
    network_wifi: float
    network_cellular: float
    network_constrained: float

    # --- relationship and history -----------------------------------------
    helper_trust_age_days_log: float
    prior_sessions_log: float
    prior_escalation_rate: float
    is_first_session: float

    def as_array(self) -> np.ndarray:
        """Return the vector in canonical column order."""
        values = asdict(self)
        return np.array([values[name] for name in FEATURE_NAMES], dtype=np.float64)

    def as_dict(self) -> dict[str, float]:
        """Return the named features, for logging into ``ml_decision_log``."""
        return {name: float(getattr(self, name)) for name in FEATURE_NAMES}


#: Canonical feature order. Derived from the dataclass so the two cannot drift.
FEATURE_NAMES: Final[tuple[str, ...]] = tuple(f.name for f in fields(FeatureVector))

N_FEATURES: Final = len(FEATURE_NAMES)


def _flag(value: Any) -> float:
    """Coerce a possibly-``None`` boolean to 0.0/1.0."""
    return 1.0 if bool(value) else 0.0


def _one_hot(value: str | None, vocabulary: Iterable[str], fallback: str) -> dict[str, float]:
    """One-hot encode with an explicit fallback bucket."""
    vocabulary = tuple(vocabulary)
    normalised = (value or "").strip().lower()
    if normalised not in vocabulary:
        normalised = fallback
    return {member: 1.0 if member == normalised else 0.0 for member in vocabulary}


def extract(
    context: Any,
    *,
    app_profile: Mapping[str, float] | None = None,
    history: Mapping[str, float] | None = None,
) -> FeatureVector:
    """Build a :class:`FeatureVector` from a context record.

    Args:
        context: Anything with the ``ContextSnapshot`` / ``ContextEvent``
            attribute names — an ORM object, or a plain object in tests and in
            the synthetic generators. Attribute access is duck-typed
            deliberately: binding this to one ORM class would force the
            training pipeline to instantiate ORM objects for millions of rows.
        app_profile: A row of ``mv_app_risk_profile`` for the foreground app,
            when one exists. Absent for an app seen fewer than five times
            across the population, which is the cold-start case.
        history: Per-relationship aggregates from ``mv_user_assistance_profile``.

    Returns:
        The feature vector, with every field finite and bounded.
    """
    profile = app_profile or {}
    hist = history or {}

    category = (getattr(context, "foreground_app_category", None) or "unknown").lower()
    categories = _one_hot(category, APP_CATEGORIES, "unknown")
    platforms = _one_hot(getattr(context, "platform", None), PLATFORMS, "unknown")
    network = _one_hot(getattr(context, "network_type", None), NETWORK_TYPES, "unknown")

    battery = getattr(context, "battery_percent", None)
    battery_value = 1.0 if battery is None else max(0.0, min(100.0, float(battery))) / 100.0

    observations = float(profile.get("observation_count", 0.0) or 0.0)

    prior_sessions = float(hist.get("prior_sessions", 0.0) or 0.0)
    trust_age_days = float(hist.get("trust_age_days", 0.0) or 0.0)

    return FeatureVector(
        is_flag_secure_active=_flag(getattr(context, "is_flag_secure_active", False)),
        is_sensitive_app=_flag(getattr(context, "is_sensitive_app", False)),
        is_critical_category=1.0 if category in CRITICAL_CATEGORIES else 0.0,
        category_banking=categories["banking"],
        category_payment=categories["payment"],
        category_health=categories["health"],
        category_password_manager=categories["password_manager"],
        category_messaging=categories["messaging"],
        category_social=categories["social"],
        category_productivity=categories["productivity"],
        category_system=categories["system"],
        category_media=categories["media"],
        category_unknown=categories["unknown"],
        app_high_risk_rate=float(profile.get("high_risk_rate", 0.0) or 0.0),
        app_sensitive_rate=float(profile.get("sensitive_rate", 0.0) or 0.0),
        # Confidence in the population prior, saturating with evidence. A rate
        # from five observations and one from five thousand are not equally
        # informative, and a linear count would let one popular app dominate
        # the scale.
        app_observation_weight=float(np.log1p(observations) / np.log1p(1000.0)),
        accessibility_enabled=_flag(getattr(context, "accessibility_enabled", False)),
        accessibility_gesture_capable=_flag(
            getattr(context, "accessibility_gesture_capable", False)
        ),
        screen_share_permission=_flag(getattr(context, "screen_share_permission", False)),
        microphone_permission=_flag(getattr(context, "microphone_permission", False)),
        remote_control_permission=_flag(
            getattr(context, "remote_control_permission", False)
        ),
        is_screen_sharing=_flag(getattr(context, "is_screen_sharing", False)),
        platform_android=platforms["android"],
        platform_ios=platforms["ios"],
        platform_web=platforms["web"],
        platform_unknown=platforms["unknown"],
        battery_normalised=battery_value,
        # A separate low-battery indicator, because the effect is a threshold
        # rather than a slope: a session is at risk of ending abruptly below
        # roughly 15%, and nothing much changes between 60% and 90%.
        battery_is_low=1.0 if battery_value < 0.15 else 0.0,
        is_charging=_flag(getattr(context, "is_charging", False)),
        network_wifi=network["wifi"],
        network_cellular=network["cellular"],
        network_constrained=network["cellular"] + network["none"],
        helper_trust_age_days_log=float(np.log1p(max(0.0, trust_age_days)) / np.log1p(365.0)),
        prior_sessions_log=float(np.log1p(max(0.0, prior_sessions)) / np.log1p(100.0)),
        prior_escalation_rate=float(hist.get("escalation_rate", 0.0) or 0.0),
        is_first_session=1.0 if prior_sessions < 1 else 0.0,
    )


def to_matrix(vectors: Iterable[FeatureVector]) -> np.ndarray:
    """Stack feature vectors into an ``(n_samples, n_features)`` matrix."""
    stacked = [vector.as_array() for vector in vectors]
    if not stacked:
        return np.empty((0, N_FEATURES), dtype=np.float64)
    return np.vstack(stacked)
