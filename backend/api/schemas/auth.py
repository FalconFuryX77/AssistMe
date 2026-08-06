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
    """Response for token refresh (access token only)."""

    access_token: str
    token_type: str = "bearer"


class MessageResponse(BaseModel):
    """Generic message response."""

    detail: str
