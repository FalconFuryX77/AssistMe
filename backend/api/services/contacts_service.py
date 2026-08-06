"""Trusted contacts business logic."""

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.trusted_contact import TrustedContact
from models.user import User


class ContactsService:
    """Manages trusted-contact relationships between users."""

    @staticmethod
    async def create_contact(
        user_id: str,
        contact_email: str,
        db: AsyncSession,
    ) -> TrustedContact:
        """Send a contact request to another user by email.

        Raises:
            400 – self-add or duplicate request
            404 – target user not found
        """
        # Find the target user
        result = await db.execute(select(User).where(User.email == contact_email))
        contact_user = result.scalar_one_or_none()

        if contact_user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        if contact_user.id == user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot add yourself as a contact",
            )

        # Check for existing request (in either direction)
        result = await db.execute(
            select(TrustedContact).where(
                or_(
                    (TrustedContact.user_id == user_id)
                    & (TrustedContact.contact_user_id == contact_user.id),
                    (TrustedContact.user_id == contact_user.id)
                    & (TrustedContact.contact_user_id == user_id),
                )
            )
        )
        if result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Contact request already exists",
            )

        contact = TrustedContact(
            user_id=user_id,
            contact_user_id=contact_user.id,
        )
        db.add(contact)
        await db.commit()
        await db.refresh(contact)
        return contact

    @staticmethod
    async def list_contacts(
        user_id: str,
        status_filter: str | None,
        db: AsyncSession,
    ) -> list[dict]:
        """List all contacts for a user, optionally filtered by status.

        Returns enriched dicts with contact email and display name.
        """
        query = select(TrustedContact).where(
            or_(
                TrustedContact.user_id == user_id,
                TrustedContact.contact_user_id == user_id,
            )
        )
        if status_filter:
            query = query.where(TrustedContact.status == status_filter)

        result = await db.execute(query)
        contacts = result.scalars().all()

        # Enrich with contact user details
        enriched = []
        for c in contacts:
            # Determine which side is "the other person"
            other_id = c.contact_user_id if c.user_id == user_id else c.user_id
            user_result = await db.execute(select(User).where(User.id == other_id))
            other_user = user_result.scalar_one_or_none()

            enriched.append(
                {
                    "id": c.id,
                    "user_id": c.user_id,
                    "contact_user_id": c.contact_user_id,
                    "contact_email": other_user.email if other_user else None,
                    "contact_display_name": other_user.display_name if other_user else None,
                    "status": c.status,
                    "created_at": c.created_at,
                }
            )
        return enriched

    @staticmethod
    async def update_contact_status(
        contact_id: str,
        user_id: str,
        new_status: str,
        db: AsyncSession,
    ) -> TrustedContact:
        """Accept or reject a contact request.

        Only the recipient (contact_user_id) can accept/reject.
        """
        if new_status not in ("accepted", "rejected"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Status must be 'accepted' or 'rejected'",
            )

        result = await db.execute(
            select(TrustedContact).where(TrustedContact.id == contact_id)
        )
        contact = result.scalar_one_or_none()

        if contact is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contact request not found",
            )

        # Only the recipient can accept/reject
        if contact.contact_user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to modify this contact request",
            )

        contact.status = new_status
        await db.commit()
        await db.refresh(contact)
        return contact

    @staticmethod
    async def delete_contact(
        contact_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> None:
        """Remove a contact. Either party can delete."""
        result = await db.execute(
            select(TrustedContact).where(TrustedContact.id == contact_id)
        )
        contact = result.scalar_one_or_none()

        if contact is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contact request not found",
            )

        if contact.user_id != user_id and contact.contact_user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to delete this contact",
            )

        await db.delete(contact)
        await db.commit()
