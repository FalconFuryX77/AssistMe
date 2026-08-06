"""Pydantic schemas for Phase 14 Performance Optimization, Hardening & Security Auditing."""

from datetime import datetime
from pydantic import BaseModel, field_validator


class ICERestartRequest(BaseModel):
    """Request body for triggering a WebRTC ICE restart."""

    reason: str = "connection_degraded"

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        if not v or len(v.strip()) == 0:
            raise ValueError("reason cannot be empty")
        return v


class ICERestartResponse(BaseModel):
    """Response containing new ICE credentials after ICE restart."""

    session_id: str
    ice_restart_triggered: bool
    ufrag: str
    pwd: str
    timestamp: datetime

    model_config = {"from_attributes": True}


class KeyZeroizeRequest(BaseModel):
    """Request body for securely wiping in-memory E2EE keys and auth state."""

    zeroize_reason: str = "session_end_privacy_scrub"


class KeyZeroizeResponse(BaseModel):
    """Response confirming zeroization of sensitive session security keys."""

    session_id: str
    zeroized: bool
    keys_scrubbed_count: int
    timestamp: datetime

    model_config = {"from_attributes": True}
