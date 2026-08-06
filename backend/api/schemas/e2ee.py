"""Pydantic schemas for Phase 8 End-to-End Encryption (E2EE) Signal Protocol & WebRTC Insertable Streams."""

from pydantic import BaseModel, field_validator


class E2EEKeyExchangeRequest(BaseModel):
    """Request body for exchanging E2EE identity keys, signed prekeys, and ephemeral ratchet keys."""

    identity_key: str
    signed_prekey: str
    ephemeral_key: str
    algorithm: str = "Signal_DoubleRatchet_AES256_GCM"

    @field_validator("algorithm")
    @classmethod
    def validate_algorithm(cls, v: str) -> str:
        if v not in ("Signal_DoubleRatchet_AES256_GCM", "WebRTC_InsertableStreams_AES_GCM"):
            raise ValueError("Supported E2EE algorithms: Signal_DoubleRatchet_AES256_GCM or WebRTC_InsertableStreams_AES_GCM")
        return v


class E2EEKeyRotationRequest(BaseModel):
    """Request body for forward secrecy key rotation and Double Ratchet updates."""

    new_ephemeral_key: str
    ratchet_counter: int


class E2EEVerificationRequest(BaseModel):
    """Request body for SAS (Short Authentication String) / Safety Number MITM fingerprint verification."""

    safety_number_fingerprint: str
    is_verified_by_user: bool = True


class E2EESecurityStatusResponse(BaseModel):
    """Response containing E2EE key exchange, active fingerprint, and MITM verification status."""

    e2ee_enabled: bool
    key_exchange_complete: bool
    fingerprint: str | None = None
    is_mitm_verified: bool = False
    session_id: str

    model_config = {"from_attributes": True}
