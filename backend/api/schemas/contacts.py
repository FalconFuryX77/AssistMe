"""Pydantic schemas for trusted contacts endpoints."""

from datetime import datetime

from pydantic import BaseModel, EmailStr


class ContactCreateRequest(BaseModel):
    """Request body for sending a contact invitation."""

    contact_email: EmailStr


class ContactStatusUpdateRequest(BaseModel):
    """Request body for accepting or rejecting a contact invitation."""

    status: str  # "accepted" or "rejected"


class ContactResponse(BaseModel):
    """Contact relationship representation returned by the API."""

    id: str
    user_id: str
    contact_user_id: str
    contact_email: str | None = None
    contact_display_name: str | None = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
