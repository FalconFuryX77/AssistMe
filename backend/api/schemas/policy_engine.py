"""Pydantic schemas for Phase 9 Adaptive Policy Engine.

Risk classification, capability negotiation, assistance mode selection, and
consent verification are the core "research core" decision flow that adapts the
assistance experience to the current device context.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# Valid assistance modes (output of the policy engine)
ASSISTANCE_MODES = ("voice", "pointer", "drawing", "tap", "restricted")

# Valid risk levels
RISK_LEVELS = ("low", "medium", "high")

# Valid capabilities
CAPABILITIES = ("voice", "pointer", "drawing", "tap", "drag", "keyboard", "restricted")


class PolicyEvaluateRequest(BaseModel):
    """Request body to (re)evaluate adaptive policy for a session."""

    user_role: str = "helper"  # who is requesting assistance capability
    requested_capabilities: list[str] | None = None
    consent_token: str | None = None  # opaque consent proof from the helpee

    @field_validator("user_role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v.lower() not in ("helper", "helpee", "observer", "secondary_helper", "primary_helper"):
            raise ValueError("user_role must be a valid participant role")
        return v.lower()


class PolicyCapabilityRequest(BaseModel):
    """Request body for explicit capability negotiation."""

    capabilities: list[str] = Field(default_factory=list)

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, v: list[str]) -> list[str]:
        lower = [c.lower() for c in v]
        for c in lower:
            if c not in CAPABILITIES:
                raise ValueError(
                    f"capability '{c}' not allowed; choose from {CAPABILITIES}"
                )
        return lower


class PolicyConsentRequest(BaseModel):
    """Request body for verifying helpee consent to a capability set."""

    consent_token: str
    capabilities: list[str] = Field(default_factory=list)

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, v: list[str]) -> list[str]:
        lower = [c.lower() for c in v]
        for c in lower:
            if c not in CAPABILITIES:
                raise ValueError(
                    f"capability '{c}' not allowed; choose from {CAPABILITIES}"
                )
        return lower


class PolicyStatusResponse(BaseModel):
    """Current policy decision for a session.

    The provenance fields exist so a decision is explainable after the fact.
    A helpee — or a family member reviewing what happened — is entitled to know
    not just what the system decided but whether a model was involved, which
    version, and whether the deterministic safety rules had to override it.
    ``decision_source`` is never absent: every decision is attributable to
    either a named model artefact or the rule engine.
    """

    session_id: str
    risk_level: str = "low"
    risk_reasons: list[str] = []
    negotiated_capabilities: list[str] = []
    assistance_mode: str = "voice"
    consent_verified: bool = False
    consent_granted_at: datetime | None = None
    evaluated_at: datetime

    # --- Decision provenance ---------------------------------------------
    #: ``"model"`` or ``"rules"``.
    decision_source: str = "rules"
    #: Registry identifier of the artefact that scored this decision.
    model_version: str | None = None
    #: Calibrated P(elevated risk), when a model produced it.
    risk_score: float | None = Field(default=None, ge=0.0, le=1.0)
    #: The model's confidence in its own output, distinct from risk_score.
    model_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    #: True when the rule-based safety envelope reduced the model's proposal.
    envelope_clamped: bool = False

    model_config = {"from_attributes": True, "protected_namespaces": ()}