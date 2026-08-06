"""Pydantic schemas for Phase 10 Multi-party Assistance Sessions & Role Management."""

from pydantic import BaseModel, field_validator
from api.schemas.sessions import ParticipantResponse


class ParticipantInviteRequest(BaseModel):
    """Request body for inviting secondary helpers or observers to a session."""

    email_or_user_id: str
    role: str = "secondary_helper"  # "primary_helper", "secondary_helper", "observer", "helpee"

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        v_lower = v.lower()
        if v_lower not in ("primary_helper", "secondary_helper", "observer", "helpee"):
            raise ValueError("role must be 'primary_helper', 'secondary_helper', 'observer', or 'helpee'")
        return v_lower


class ParticipantRoleUpdateRequest(BaseModel):
    """Request body for updating a participant's role in a session."""

    role: str  # "primary_helper", "secondary_helper", "observer", "helpee"

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        v_lower = v.lower()
        if v_lower not in ("primary_helper", "secondary_helper", "observer", "helpee"):
            raise ValueError("role must be 'primary_helper', 'secondary_helper', 'observer', or 'helpee'")
        return v_lower


class ActiveSpeakerSignalRequest(BaseModel):
    """Request body for signaling active speaker change for multi-stream layout switching."""

    active_speaker_user_id: str
    audio_level_db: float | None = 0.0


class ActiveSpeakerStatusResponse(BaseModel):
    """Response containing active speaker information for multi-stream audio/video layout routing."""

    session_id: str
    active_speaker_user_id: str | None = None
    audio_level_db: float | None = 0.0

    model_config = {"from_attributes": True}


class MultiPartyParticipantListResponse(BaseModel):
    """Response wrapper for active multi-party session participants."""

    session_id: str
    total_participants: int
    participants: list[ParticipantResponse]
