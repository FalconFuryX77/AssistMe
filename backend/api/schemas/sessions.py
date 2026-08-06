"""Pydantic schemas for session management endpoints."""

from datetime import datetime

from pydantic import BaseModel


class SessionCreateRequest(BaseModel):
    """Request body for creating a new assistance session."""

    title: str | None = None
    timeout_minutes: int = 30


class SessionJoinRequest(BaseModel):
    """Request body for joining a session by code."""

    session_code: str


class ParticipantResponse(BaseModel):
    """A participant in a session."""

    id: str
    user_id: str
    user_email: str | None = None
    user_display_name: str | None = None
    role: str
    status: str
    joined_at: datetime
    last_seen_at: datetime
    is_screen_sharing: bool = False
    screen_share_platform: str | None = None
    is_flag_secure_active: bool = False
    screen_orientation: str = "portrait"
    is_in_audio_call: bool = False
    is_audio_muted: bool = False
    audio_route: str = "speaker"
    audio_quality: str = "high"
    video_resolution: str = "720p"
    video_bitrate_kbps: int = 1500
    video_fps: int = 30
    rtt_ms: float = 50.0
    packet_loss_percent: float = 0.0

    model_config = {"from_attributes": True}


class SessionResponse(BaseModel):
    """Full session representation returned by the API."""

    id: str
    creator_id: str
    status: str
    title: str | None = None
    session_code: str
    timeout_minutes: int
    remote_control_granted: bool = False
    remote_control_granted_at: datetime | None = None
    remote_control_platform: str | None = None
    created_at: datetime
    updated_at: datetime
    ended_at: datetime | None = None
    participants: list[ParticipantResponse] = []

    model_config = {"from_attributes": True}


class SessionListItem(BaseModel):
    """Compact session representation for list endpoints."""

    id: str
    status: str
    title: str | None = None
    session_code: str
    created_at: datetime
    participant_count: int = 0

    model_config = {"from_attributes": True}


class SessionRecoverRequest(BaseModel):
    """Request body for recovering a disconnected session."""

    session_id: str
