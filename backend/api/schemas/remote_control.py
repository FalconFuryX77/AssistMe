"""Pydantic schemas for Remote Control Protocol (Accessibility Service / AssistiveTouch gesture injection)."""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field, field_validator, model_validator


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
    x: float | None = Field(default=None, ge=0.0)
    y: float | None = Field(default=None, ge=0.0)
    normalized_x: float | None = Field(default=None, ge=0.0, le=1.0)  # screen-size-agnostic dispatch
    normalized_y: float | None = Field(default=None, ge=0.0, le=1.0)
    end_x: float | None = Field(default=None, ge=0.0)
    end_y: float | None = Field(default=None, ge=0.0)
    duration_ms: int | None = Field(default=300, ge=1, le=5000)
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

    @model_validator(mode="after")
    def validate_event_payload(self) -> "RemoteControlInputEvent":
        """Reject malformed gestures before they reach a native input service."""
        has_point = self.normalized_x is not None and self.normalized_y is not None
        has_absolute_point = self.x is not None and self.y is not None

        if self.event_type in {"tap", "long_press"} and not (
            has_point or has_absolute_point
        ):
            raise ValueError("tap and long_press require x/y or normalized_x/normalized_y")

        if self.event_type == "drag":
            has_end_point = self.end_x is not None and self.end_y is not None
            if not ((has_point or has_absolute_point) and has_end_point):
                raise ValueError("drag requires start and end coordinates")

        if self.event_type == "key_event":
            valid_keys = {
                "back",
                "home",
                "recents",
                "notifications",
                "volume_up",
                "volume_down",
            }
            if self.key_code not in valid_keys:
                raise ValueError(f"key_code must be one of {sorted(valid_keys)}")

        return self


class RemoteControlStatusResponse(BaseModel):
    """Response showing current remote control authorization state."""

    remote_control_granted: bool
    remote_control_granted_at: datetime | None = None
    remote_control_platform: str | None = None
    session_id: str

    model_config = {"from_attributes": True}
