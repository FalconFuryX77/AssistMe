"""Pydantic schemas for the assistance request & escalation flow."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# Capabilities that a helper may be granted.
VALID_CAPABILITIES = ("overlay_draw", "pointer", "tap", "drag", "voice")


class AssistanceRequestCreate(BaseModel):
    """Body for a helpee to request help (one-click)."""

    helper_user_id: str
    helper_device_fingerprint: str = Field(min_length=16, max_length=128)


class AssistanceRequestResponse(BaseModel):
    """An assistance request."""

    id: str
    session_id: str
    helpee_user_id: str
    helper_user_id: str | None = None
    helper_device_fingerprint: str | None = None
    status: str
    initial_capabilities: list[str] = Field(default_factory=list)
    responded_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AssistanceRequestRespond(BaseModel):
    """Helper's accept/deny response to an assistance request."""

    accept: bool
    helper_device_fingerprint: str | None = None


class EscalationCreate(BaseModel):
    """A helper requests more control than the current (overlay-only) mode."""

    target_capabilities: list[str] = Field(default_factory=list)

    @field_validator("target_capabilities")
    @classmethod
    def validate_caps(cls, v: list[str]) -> list[str]:
        lower = [c.lower() for c in v]
        for c in lower:
            if c not in VALID_CAPABILITIES:
                raise ValueError(
                    f"capability '{c}' not allowed; choose from {VALID_CAPABILITIES}"
                )
        return lower


class EscalationResponse(BaseModel):
    """An escalation request with its risk disclaimer."""

    id: str
    session_id: str
    requested_by_user_id: str
    target_capabilities: list[str]
    status: str
    disclaimer_text: str | None = None
    disclaimer_accepted: bool = False
    granted_capabilities: list[str] = Field(default_factory=list)
    responded_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class EscalationRespond(BaseModel):
    """Helpee's response to an escalation — must explicitly accept the risks."""

    accept: bool
    accept_disclaimer: bool = False
