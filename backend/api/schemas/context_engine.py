"""Pydantic schemas for Phase 8 Context Engine.

The Context Engine collects and exposes real-time device & session context for
each participant: platform, foreground app, accessibility state, permissions,
screen sharing / security state, and session state.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ContextReportRequest(BaseModel):
    """Client-reported context snapshot (all fields optional, updated in place)."""

    platform: str | None = None  # "android", "ios", "web", "unknown"
    os_version: str | None = None
    device_model: str | None = None
    screen_width: int | None = None
    screen_height: int | None = None
    screen_density: float | None = None
    foreground_app: str | None = None
    foreground_app_category: str | None = None
    is_sensitive_app: bool | None = None
    accessibility_enabled: bool | None = None
    accessibility_gesture_capable: bool | None = None
    screen_share_permission: bool | None = None
    microphone_permission: bool | None = None
    remote_control_permission: bool | None = None
    is_screen_sharing: bool | None = None
    is_flag_secure_active: bool | None = None
    is_in_audio_call: bool | None = None
    battery_percent: int | None = Field(default=None, ge=0, le=100)
    is_charging: bool | None = None
    network_type: str | None = None  # "wifi", "cellular", "ethernet", "none", "unknown"

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str | None) -> str | None:
        if v is not None and v.lower() not in ("android", "ios", "web", "unknown"):
            raise ValueError("platform must be 'android', 'ios', 'web', or 'unknown'")
        return v.lower() if v else v

    @field_validator("network_type")
    @classmethod
    def validate_network(cls, v: str | None) -> str | None:
        if v is not None and v.lower() not in ("wifi", "cellular", "ethernet", "none", "unknown"):
            raise ValueError("network_type must be 'wifi', 'cellular', 'ethernet', 'none', or 'unknown'")
        return v.lower() if v else v


class ContextSnapshotResponse(BaseModel):
    """Full context snapshot returned by the API."""

    session_id: str
    user_id: str
    platform: str = "unknown"
    os_version: str | None = None
    device_model: str | None = None
    screen_width: int | None = None
    screen_height: int | None = None
    screen_density: float | None = None
    foreground_app: str | None = None
    foreground_app_category: str | None = None
    is_sensitive_app: bool = False
    accessibility_enabled: bool = False
    accessibility_gesture_capable: bool = False
    screen_share_permission: bool = False
    microphone_permission: bool = False
    remote_control_permission: bool = False
    is_screen_sharing: bool = False
    is_flag_secure_active: bool = False
    is_in_audio_call: bool = False
    role: str = "helpee"
    session_status: str = "waiting"
    battery_percent: int | None = None
    is_charging: bool | None = None
    network_type: str | None = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContextHistoryResponse(BaseModel):
    """Wrapper for a list of context snapshots across session participants."""

    session_id: str
    total_snapshots: int
    snapshots: list[ContextSnapshotResponse]
