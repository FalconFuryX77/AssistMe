"""Pydantic schemas for authentication endpoints."""

import re

from pydantic import BaseModel, EmailStr, field_validator


class RegisterRequest(BaseModel):
    """Request body for user registration."""

    email: EmailStr
    password: str
    display_name: str | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one digit")
        return v


class LoginRequest(BaseModel):
    """Request body for user login."""

    email: EmailStr
    password: str


class RefreshTokenRequest(BaseModel):
    """Request body for token refresh and logout."""

    refresh_token: str


class AuthResponse(BaseModel):
    """Response for register and login (contains both tokens)."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AccessTokenResponse(BaseModel):
    """Response for token refresh."""

    access_token: str
    token_type: str = "bearer"
    refresh_token: str | None = None


class MessageResponse(BaseModel):
    """Generic message response."""

    detail: str


class DeviceBootstrapRequest(BaseModel):
    """Device-first registration/login — no email or password, ever.

    The client sends its stable install fingerprint and an optional
    device_secret to authenticate returning logins.
    """

    device_fingerprint: str
    display_name: str | None = None
    device_secret: str | None = None

    @field_validator("device_fingerprint")
    @classmethod
    def fingerprint_shape(cls, v: str) -> str:
        if len(v) < 16 or len(v) > 128:
            raise ValueError("Device fingerprint must be 16-128 characters")
        return v

    @field_validator("display_name")
    @classmethod
    def name_length(cls, v: str | None) -> str | None:
        if v is not None and (len(v.strip()) < 1 or len(v) > 60):
            raise ValueError("Display name must be 1-60 characters")
        return v.strip() if v else v


class DeviceBootstrapResponse(BaseModel):
    """Result of device bootstrap.

    `recovery_code` is returned exactly once, on the call that created the
    identity; it is the root credential for reclaiming after reinstall.
    `device_secret` is the cryptographic secret for authenticating the device.
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    display_name: str | None = None
    created: bool
    recovery_code: str | None = None
    device_secret: str | None = None
