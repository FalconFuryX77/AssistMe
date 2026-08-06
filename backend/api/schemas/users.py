"""Pydantic schemas for user profile endpoints."""

from datetime import datetime

from pydantic import BaseModel


class UserResponse(BaseModel):
    """Public user profile."""

    id: str
    email: str
    display_name: str | None = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdateRequest(BaseModel):
    """Request body for updating user profile fields."""

    display_name: str | None = None
