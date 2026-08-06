"""Pydantic schemas for Screen Sharing control, status, and security events."""

from pydantic import BaseModel, field_validator


class ScreenShareStartRequest(BaseModel):
    """Request body for starting screen sharing."""

    platform: str  # "android" (MediaProjection) or "ios" (ReplayKit)
    orientation: str = "portrait"  # "portrait" or "landscape"
    width: int | None = 1080
    height: int | None = 1920
    fps: int = 30

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        v_lower = v.lower()
        if v_lower not in ("android", "ios"):
            raise ValueError("Platform must be 'android' or 'ios'")
        return v_lower

    @field_validator("orientation")
    @classmethod
    def validate_orientation(cls, v: str) -> str:
        v_lower = v.lower()
        if v_lower not in ("portrait", "landscape"):
            raise ValueError("Orientation must be 'portrait' or 'landscape'")
        return v_lower


class ScreenShareStopRequest(BaseModel):
    """Request body for stopping screen sharing."""

    reason: str | None = "user_stopped"  # "user_stopped", "session_interrupted", "permission_revoked"


class ScreenShareOrientationRequest(BaseModel):
    """Request body for updating screen share orientation."""

    orientation: str  # "portrait" or "landscape"

    @field_validator("orientation")
    @classmethod
    def validate_orientation(cls, v: str) -> str:
        v_lower = v.lower()
        if v_lower not in ("portrait", "landscape"):
            raise ValueError("Orientation must be 'portrait' or 'landscape'")
        return v_lower


class ScreenShareSecurityEventRequest(BaseModel):
    """Request body for security events (FLAG_SECURE, protected apps, backgrounding)."""

    event_type: str  # "flag_secure_enabled", "flag_secure_disabled", "protected_app_entered", "protected_app_exited", "app_backgrounded", "app_foregrounded"
    detail: str | None = None


class ScreenShareStatusResponse(BaseModel):
    """Response showing current screen sharing state for a participant/session."""

    is_screen_sharing: bool
    platform: str | None = None
    is_flag_secure_active: bool = False
    screen_orientation: str = "portrait"
    participant_user_id: str | None = None

    model_config = {"from_attributes": True}
