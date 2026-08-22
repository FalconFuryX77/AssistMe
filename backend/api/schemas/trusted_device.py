"""Pydantic schemas for trusted device endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field


class TrustedDeviceResponse(BaseModel):
    """A trusted device representation returned by the API."""

    id: str
    owner_user_id: str
    device_fingerprint: str
    friendly_name: str | None = None
    device_platform: str | None = None
    status: str
    last_seen_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TrustedDeviceListResponse(BaseModel):
    """List of trusted devices for a user."""

    total: int
    devices: list[TrustedDeviceResponse]


class DevicePairingRequest(BaseModel):
    """Request to initiate a new device pairing (from the device itself)."""

    device_fingerprint: str = Field(min_length=16, max_length=128)
    friendly_name: str | None = Field(default=None, max_length=100)
    device_platform: str | None = Field(default=None, max_length=30)


class DevicePairingResponse(BaseModel):
    """Response containing the pairing code (shown to the device owner)."""

    pairing_id: str
    pairing_code: str
    expires_at: datetime


class DevicePairingConfirmRequest(BaseModel):
    """Confirm a pairing code (requires the owner's password)."""

    pairing_code: str = Field(min_length=4, max_length=12)
    password: str


class DevicePairingConfirmResponse(BaseModel):
    """Result of confirming a pairing."""

    device_id: str
    device_fingerprint: str
    friendly_name: str | None = None
    status: str


class DeviceSetupCodeRequest(BaseModel):
    """Generate a setup code the owner reads aloud to a helper."""

    friendly_name: str | None = Field(default=None, max_length=100)


class DeviceSetupCodeResponse(BaseModel):
    """A one-time setup code the owner reads to the helper."""

    pairing_id: str
    setup_code: str
    expires_at: datetime


class DeviceClaimRequest(BaseModel):
    """Helper claims a pairing by entering the code they heard aloud."""

    setup_code: str = Field(min_length=4, max_length=12)
    device_fingerprint: str = Field(min_length=16, max_length=128)
    friendly_name: str | None = Field(default=None, max_length=100)
    device_platform: str | None = Field(default=None, max_length=30)


class DeviceClaimResponse(BaseModel):
    """Result of claiming a pairing (now awaiting owner approval)."""

    pairing_id: str
    status: str


class PendingPairingResponse(BaseModel):
    """A claimed pairing awaiting the owner's one-tap approval."""

    pairing_id: str
    device_fingerprint: str
    friendly_name: str | None = None
    device_platform: str | None = None
    expires_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}

    @classmethod
    def from_pairing(cls, pairing: object) -> "PendingPairingResponse":
        """Build from a DevicePairing ORM object (maps `id` -> `pairing_id`)."""
        return cls(
            pairing_id=pairing.id,
            device_fingerprint=pairing.device_fingerprint,
            friendly_name=pairing.friendly_name,
            device_platform=pairing.device_platform,
            expires_at=pairing.expires_at,
            created_at=pairing.created_at,
        )


class PendingPairingsResponse(BaseModel):
    """Pending pairings awaiting the owner's approval."""

    total: int
    pairings: list[PendingPairingResponse]


class DeviceApproveRequest(BaseModel):
    """Owner approves a claimed pairing with one tap (no password)."""

    pairing_id: str


class DeviceApproveResponse(BaseModel):
    """Result of approving a pairing."""

    device_id: str
    device_fingerprint: str
    friendly_name: str | None = None
    status: str


class TrustedDeviceManageRequest(BaseModel):
    """Manage (revoke) a trusted device — requires password re-auth."""

    password: str


class PasswordVerifyRequest(BaseModel):
    """Re-authenticate the user with their password (protects the trusted list)."""

    password: str


class DeviceAuthRequest(BaseModel):
    """A device presents its fingerprint + proof to act as a helper."""

    device_fingerprint: str = Field(min_length=16, max_length=128)


class DeviceAuthResponse(BaseModel):
    """Result of a device identity check."""

    is_trusted: bool
    status: str
    device_id: str | None = None
    friendly_name: str | None = None
