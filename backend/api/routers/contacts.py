"""Trusted contacts API routes."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas.contacts import (
    ContactCreateRequest,
    ContactResponse,
    ContactStatusUpdateRequest,
)
from api.services.contacts_service import ContactsService
from core.database import get_db
from models.user import User

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.post(
    "/",
    response_model=ContactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_contact(
    payload: ContactCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Send a contact request to another user."""
    contact = await ContactsService.create_contact(
        user_id=current_user.id,
        contact_email=payload.contact_email,
        db=db,
    )
    return {
        "id": contact.id,
        "user_id": contact.user_id,
        "contact_user_id": contact.contact_user_id,
        "status": contact.status,
        "created_at": contact.created_at,
    }


@router.get("/", response_model=list[ContactResponse])
async def list_contacts(
    status_filter: str | None = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all contacts for the authenticated user."""
    return await ContactsService.list_contacts(
        user_id=current_user.id,
        status_filter=status_filter,
        db=db,
    )


@router.patch("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: str,
    payload: ContactStatusUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept or reject a contact request."""
    contact = await ContactsService.update_contact_status(
        contact_id=contact_id,
        user_id=current_user.id,
        new_status=payload.status,
        db=db,
    )
    return {
        "id": contact.id,
        "user_id": contact.user_id,
        "contact_user_id": contact.contact_user_id,
        "status": contact.status,
        "created_at": contact.created_at,
    }


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a trusted contact."""
    await ContactsService.delete_contact(
        contact_id=contact_id,
        user_id=current_user.id,
        db=db,
    )
