"""The safety envelope: deterministic bounds no model output can exceed.

The central design decision of this system
-------------------------------------------
A learned policy decides what a stranger-to-the-model helper may do on an
elderly person's phone. Machine learning is the right tool for *choosing well
within* that space, and the wrong tool for *defining its boundary*, for three
reasons that are properties of the deployment rather than of the algorithm:

* A model retrained on new data can regress in ways no test catches until it is
  live, and the failure mode here is a stranger tapping inside someone's bank
  app.
* A model is an attack surface. Features come from the client, and a
  compromised or modified client can craft the context vector it wants. Rules
  that key on the two signals the OS itself sets — ``FLAG_SECURE`` and the
  accessibility capability — are correspondingly harder to talk out of.
* Consent is a legal and ethical property, not a statistical one. "The model
  estimated the user probably would have agreed" is not consent.

So the model never *grants*. It proposes; the envelope decides what the
proposal is allowed to become. Formally, for context ``x``::

    ceiling(x) = the highest-privilege mode the rules permit
    action     = min(model_proposal, ceiling(x))          [by privilege rank]

The clamp is one-directional. The envelope can lower a proposal and never raise
one, so the worst a broken model can do is be unhelpful. It is enforced three
times over — here, by the ``ck_policy_decisions_high_risk_limits_mode`` CHECK
constraint in the database, and by the client's own consent gate — because a
single point of enforcement for a safety property is a single point of failure.

This module is deliberately dependency-free and readable end to end. It is the
part of the system that should be auditable by someone who does not read
Python well.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from ml.config import ACTIONS

__all__ = [
    "CRITICAL_CATEGORIES",
    "EnvelopeDecision",
    "SafetyEnvelope",
]

#: Privilege rank. Higher means the helper can do more to the device.
_RANK: Final[dict[str, int]] = {action: i for i, action in enumerate(ACTIONS)}

#: App categories whose contents are financially or medically sensitive.
CRITICAL_CATEGORIES: Final = frozenset(
    {"banking", "payment", "health", "password_manager"}
)


@dataclass
class EnvelopeDecision:
    """The outcome of applying the envelope to a proposal."""

    #: The mode actually permitted.
    action: str
    #: The highest mode the rules would have allowed in this context.
    ceiling: str
    #: What the model proposed, before clamping.
    proposed: str
    #: True when the ceiling reduced the proposal.
    clamped: bool
    #: Plain-language justifications, shown to the helpee verbatim.
    reasons: list[str] = field(default_factory=list)
    #: Risk level the rules assign, independent of any model.
    rule_risk_level: str = "low"

    @property
    def admissible_actions(self) -> list[str]:
        """Every mode at or below the ceiling."""
        return [a for a in ACTIONS if _RANK[a] <= _RANK[self.ceiling]]


class SafetyEnvelope:
    """Computes the rule-based ceiling and clamps model proposals to it."""

    @staticmethod
    def ceiling(context: Any) -> tuple[str, str, list[str]]:
        """Return ``(ceiling_mode, rule_risk_level, reasons)`` for a context.

        The rules, in order of severity:

        1. **FLAG_SECURE is active.** The operating system has been told by the
           foreground app that its window must not be captured. Honouring that
           is not optional: the app has asserted its content is protected, and
           the ceiling drops to ``voice`` — the helper can still talk the
           person through it, which is the whole point of not going all the way
           to ``restricted``.

        2. **A critical-category app is in the foreground.** Banking, payment,
           health, and password managers. Ceiling ``voice``.

        3. **The client flags the content as sensitive.** A weaker signal than
           the two above, so it caps at ``drawing`` — annotation is still
           possible, gesture control is not.

        4. **No gesture capability.** ``tap`` requires a working accessibility
           service; without it the mode is not merely unwise but non-functional,
           so it is removed regardless of risk.
        """
        reasons: list[str] = []
        ceiling = "tap"
        risk_level = "low"

        if bool(getattr(context, "is_flag_secure_active", False)):
            reasons.append(
                "The app on screen has marked its content as protected, so "
                "only voice guidance is available."
            )
            ceiling = "voice"
            risk_level = "high"

        category = str(
            getattr(context, "foreground_app_category", "") or ""
        ).strip().lower()
        if category in CRITICAL_CATEGORIES:
            reasons.append(
                f"A {category.replace('_', ' ')} app is open, so remote "
                "control and drawing are switched off."
            )
            ceiling = _lower(ceiling, "voice")
            risk_level = "high"

        if bool(getattr(context, "is_sensitive_app", False)) and risk_level != "high":
            reasons.append(
                "This app may be showing personal information, so remote "
                "control is switched off."
            )
            ceiling = _lower(ceiling, "drawing")
            risk_level = "medium"

        if not bool(getattr(context, "accessibility_gesture_capable", False)):
            if _RANK[ceiling] >= _RANK["tap"]:
                reasons.append(
                    "Remote control is not set up on this device, so the "
                    "helper can guide but not tap."
                )
            ceiling = _lower(ceiling, "drawing")

        return ceiling, risk_level, reasons

    @staticmethod
    def apply(context: Any, proposed: str) -> EnvelopeDecision:
        """Clamp ``proposed`` to the ceiling permitted for ``context``.

        Args:
            context: The device context.
            proposed: The mode the model (or a caller) wants.

        Returns:
            An :class:`EnvelopeDecision`. ``action`` is never more privileged
            than ``ceiling``, whatever ``proposed`` was — including when
            ``proposed`` is an unrecognised string, which is treated as the
            most restrictive mode rather than passed through.
        """
        ceiling, risk_level, reasons = SafetyEnvelope.ceiling(context)

        if proposed not in _RANK:
            # An unknown mode is a bug or an injection attempt. Failing closed
            # costs the user some convenience; failing open costs them control
            # of their device.
            proposed = "restricted"
            reasons.append(
                "The requested assistance mode was not recognised, so the "
                "safest option was used."
            )

        action = proposed if _RANK[proposed] <= _RANK[ceiling] else ceiling

        return EnvelopeDecision(
            action=action,
            ceiling=ceiling,
            proposed=proposed,
            clamped=action != proposed,
            reasons=reasons,
            rule_risk_level=risk_level,
        )

    @staticmethod
    def admissible(context: Any) -> list[str]:
        """The action set a policy may choose from in this context."""
        ceiling, _, _ = SafetyEnvelope.ceiling(context)
        return [a for a in ACTIONS if _RANK[a] <= _RANK[ceiling]]

    @staticmethod
    def rule_only_mode(context: Any) -> EnvelopeDecision:
        """The decision the deterministic rules make with no model at all.

        This is the fallback whenever the model is disabled, unavailable, too
        slow, or abstaining — and it is also the baseline the evaluation
        compares learned policies against. Both uses being the same code is
        deliberate: the baseline reported in the results is exactly the
        behaviour production falls back to, not an idealised version of it.

        The rule policy takes the full ceiling. That is the least-conservative
        choice the rules permit, which makes it a *strong* baseline rather than
        a straw man — the learned policy has to beat rules operating at their
        best.
        """
        ceiling, risk_level, reasons = SafetyEnvelope.ceiling(context)
        return EnvelopeDecision(
            action=ceiling,
            ceiling=ceiling,
            proposed=ceiling,
            clamped=False,
            reasons=reasons,
            rule_risk_level=risk_level,
        )


def _lower(current: str, candidate: str) -> str:
    """Return whichever of two modes is less privileged."""
    return candidate if _RANK[candidate] < _RANK[current] else current
