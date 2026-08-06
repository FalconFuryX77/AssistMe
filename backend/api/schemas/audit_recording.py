"""Pydantic schemas for Phase 9 Session Recording & Audit Trails."""

from datetime import datetime
from pydantic import BaseModel, field_validator


class RecordingConsentRequest(BaseModel):
    """Request body for updating session recording consent."""

    consent_granted: bool
    recording_scope: str = "screen_and_audio"  # "screen_and_audio", "screen_only", "audio_only"

    @field_validator("recording_scope")
    @classmethod
    def validate_scope(cls, v: str) -> str:
        v_lower = v.lower()
        if v_lower not in ("screen_and_audio", "screen_only", "audio_only"):
            raise ValueError("recording_scope must be 'screen_and_audio', 'screen_only', or 'audio_only'")
        return v_lower


class RecordingStartRequest(BaseModel):
    """Request body for initiating session recording."""

    storage_provider: str = "local_encrypted"


class RecordingStopRequest(BaseModel):
    """Request body for stopping session recording and saving metadata."""

    file_url: str
    file_size_bytes: int
    duration_seconds: int


class RecordingStatusResponse(BaseModel):
    """Response containing active recording status and storage metadata."""

    is_recording: bool
    consent_granted: bool
    recording_scope: str | None = None
    recording_url: str | None = None
    file_size_bytes: int | None = None
    duration_seconds: int | None = None
    session_id: str

    model_config = {"from_attributes": True}


class AuditEventItem(BaseModel):
    """Individual structured audit trail event item."""

    id: str
    session_id: str
    user_id: str | None = None
    event_type: str
    detail: str | None = None
    timestamp: datetime

    model_config = {"from_attributes": True}


class AuditTrailResponse(BaseModel):
    """Response wrapper for session audit logs."""

    session_id: str
    total_events: int
    events: list[AuditEventItem]
