"""Pydantic schemas for WebRTC signaling (ICE servers, SDP Offer/Answer, ICE candidates)."""

from typing import Any
from pydantic import BaseModel


class ICEServerEntry(BaseModel):
    """STUN/TURN server configuration format for WebRTC clients (RTCIceServer compliant)."""

    urls: list[str] | str
    username: str | None = None
    credential: str | None = None


class ICEServersResponse(BaseModel):
    """Response containing ICE servers for a WebRTC session."""

    ice_servers: list[ICEServerEntry]


class SDPOfferMessage(BaseModel):
    """WebRTC SDP offer payload from helper/helpee."""

    type: str = "offer"
    sdp: str
    target_user_id: str | None = None


class SDPAnswerMessage(BaseModel):
    """WebRTC SDP answer payload."""

    type: str = "answer"
    sdp: str
    target_user_id: str | None = None


class ICECandidateMessage(BaseModel):
    """WebRTC ICE Candidate payload."""

    type: str = "candidate"
    candidate: dict[str, Any]
    target_user_id: str | None = None
