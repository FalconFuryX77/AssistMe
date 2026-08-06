"""Pydantic schemas for Remote Control Protocol (Accessibility Service / AssistiveTouch gesture injection)."""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, field_validator


class RemoteControlGrantRequest(BaseModel):
    """Request body for granting remote control access."""

    platform: str = "android_accessibility"  # "android_accessibility" or "ios_assistivetouch"

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        v_lower = v.lower()
        if v_lower not in ("android_accessibility", "ios_assistivetouch"):
            raise ValueError("platform must be 'android_accessibility' or 'ios_assistivetouch'")
        return v_lower


class RemoteControlInputEvent(BaseModel):
    """Payload representing a remote touch gesture or hardware key injection."""

    event_type: str  # "tap", "drag", "long_press", "gesture", "key_event"
    x: float | None = None
    y: float | None = None
    normalized_x: float | None = None  # 0.0 to 1.0 for screen-size-agnostic dispatch
    normalized_y: float | None = None
    end_x: float | None = None
    end_y: float | None = None
    duration_ms: int | None = 300
    key_code: str | None = None  # "back", "home", "recents", "volume_up", "volume_down"
    points: list[dict[str, float]] | None = None

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        v_lower = v.lower()
        valid_events = ("tap", "drag", "long_press", "gesture", "key_event")
        if v_lower not in valid_events:
            raise ValueError(f"event_type must be one of {valid_events}")
        return v_lower


class RemoteControlStatusResponse(BaseModel):
    """Response showing current remote control authorization state."""

    remote_control_granted: bool
    remote_control_granted_at: datetime | None = None
    remote_control_platform: str | None = None
    session_id: str

    model_config = {"from_attributes": True}
