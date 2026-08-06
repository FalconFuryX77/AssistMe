"""Pydantic schemas for Voice Communication (Audio Calls, Mute, Audio Routing, Network Degradation)."""

from pydantic import BaseModel, field_validator


class AudioCallStartRequest(BaseModel):
    """Request body for starting an audio call in a session."""

    is_muted: bool = False
    audio_route: str = "speaker"  # "speaker", "earpiece", "bluetooth", "headset"

    @field_validator("audio_route")
    @classmethod
    def validate_audio_route(cls, v: str) -> str:
        v_lower = v.lower()
        if v_lower not in ("speaker", "earpiece", "bluetooth", "headset"):
            raise ValueError("audio_route must be 'speaker', 'earpiece', 'bluetooth', or 'headset'")
        return v_lower


class AudioMuteToggleRequest(BaseModel):
    """Request body for toggling audio mute state."""

    is_muted: bool


class AudioRouteChangeRequest(BaseModel):
    """Request body for changing audio output route."""

    audio_route: str  # "speaker", "earpiece", "bluetooth", "headset"

    @field_validator("audio_route")
    @classmethod
    def validate_audio_route(cls, v: str) -> str:
        v_lower = v.lower()
        if v_lower not in ("speaker", "earpiece", "bluetooth", "headset"):
            raise ValueError("audio_route must be 'speaker', 'earpiece', 'bluetooth', or 'headset'")
        return v_lower


class AudioDegradationReportRequest(BaseModel):
    """Request body for reporting network degradation or audio quality changes."""

    quality_level: str  # "high", "medium", "low"
    packet_loss: float | None = 0.0

    @field_validator("quality_level")
    @classmethod
    def validate_quality_level(cls, v: str) -> str:
        v_lower = v.lower()
        if v_lower not in ("high", "medium", "low"):
            raise ValueError("quality_level must be 'high', 'medium', or 'low'")
        return v_lower


class AudioStatusResponse(BaseModel):
    """Response containing active audio call state for a participant or session."""

    is_in_audio_call: bool
    is_audio_muted: bool = False
    audio_route: str = "speaker"
    audio_quality: str = "high"
    participant_user_id: str | None = None

    model_config = {"from_attributes": True}
