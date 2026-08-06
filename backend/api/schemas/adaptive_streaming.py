"""Pydantic schemas for Phase 7 Adaptive Streaming & Network Optimization."""

from pydantic import BaseModel, field_validator


class StreamAdaptRequest(BaseModel):
    """Manual or automated stream quality scaling request."""

    video_resolution: str | None = None  # "1080p", "720p", "480p", "360p"
    video_bitrate_kbps: int | None = None
    video_fps: int | None = None  # 60, 30, 15, 10

    @field_validator("video_resolution")
    @classmethod
    def validate_resolution(cls, v: str | None) -> str | None:
        if v is not None:
            v_lower = v.lower()
            if v_lower not in ("1080p", "720p", "480p", "360p"):
                raise ValueError("video_resolution must be '1080p', '720p', '480p', or '360p'")
            return v_lower
        return v


class NetworkMetricsReportRequest(BaseModel):
    """Client network metrics report for automated bandwidth estimation and RTT adaptation."""

    rtt_ms: float
    jitter_ms: float | None = 0.0
    packet_loss_percent: float
    available_bandwidth_kbps: int | None = None


class StreamConfigResponse(BaseModel):
    """Current WebRTC video streaming configuration and quality parameters."""

    video_resolution: str
    video_bitrate_kbps: int
    video_fps: int
    rtt_ms: float
    packet_loss_percent: float
    auto_adapted: bool = False
    participant_user_id: str

    model_config = {"from_attributes": True}
