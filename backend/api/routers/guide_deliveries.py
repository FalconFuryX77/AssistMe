"""Post-session guide hand-off.

When the live call ends before the helper's finished guide reaches the helpee,
the helper's phone uploads it here **encrypted** (AES-GCM, key agreed over the
call's peer data channel; the server never sees it). The helpee's phone lists
its pending deliveries, downloads and decrypts them, saves the guide locally
and deletes the row. Rows expire after a week.
"""

import base64
import binascii
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from core.database import get_db
from models.guide_delivery import GuideDelivery
from models.session_participant import SessionParticipant
from models.user import User

router = APIRouter(prefix="/guide-deliveries", tags=["guides"])

# A guide holds at most 32 MiB of screenshots plus text; AES-GCM adds 28 bytes.
MAX_CIPHERTEXT_BYTES = 34 * 1024 * 1024


class GuideDeliveryCreate(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    # base64 of nonce || ciphertext || tag
    ciphertext: str = Field(min_length=1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _purge_expired(db: AsyncSession) -> None:
    await db.execute(delete(GuideDelivery).where(GuideDelivery.expires_at < _now()))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_delivery(
    payload: GuideDeliveryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        ciphertext = base64.b64decode(payload.ciphertext, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ciphertext must be base64")
    if not ciphertext or len(ciphertext) > MAX_CIPHERTEXT_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "guide is too large")

    participants = (
        await db.execute(
            select(SessionParticipant.user_id).where(
                SessionParticipant.session_id == payload.session_id
            )
        )
    ).scalars().all()
    user_ids = {str(user_id) for user_id in participants}
    sender_id = str(current_user.id)
    if sender_id not in user_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not a participant of this session")
    recipients = sorted(user_ids - {sender_id})
    if len(recipients) != 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "session has no single other participant")

    await _purge_expired(db)
    # A retry replaces the previous upload for the same session.
    await db.execute(
        delete(GuideDelivery).where(
            GuideDelivery.session_id == payload.session_id,
            GuideDelivery.sender_id == sender_id,
        )
    )
    delivery = GuideDelivery(
        session_id=payload.session_id,
        sender_id=sender_id,
        recipient_id=recipients[0],
        ciphertext=ciphertext,
        size_bytes=len(ciphertext),
    )
    db.add(delivery)
    await db.commit()
    return {"id": str(delivery.id), "expires_at": delivery.expires_at}


@router.get("/pending")
async def list_pending(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _purge_expired(db)
    await db.commit()
    rows = (
        await db.execute(
            select(
                GuideDelivery.id,
                GuideDelivery.session_id,
                GuideDelivery.size_bytes,
                GuideDelivery.created_at,
            ).where(GuideDelivery.recipient_id == str(current_user.id))
        )
    ).all()
    return [
        {
            "id": str(row.id),
            "session_id": str(row.session_id),
            "size_bytes": row.size_bytes,
            "created_at": row.created_at,
        }
        for row in rows
    ]


async def _own_delivery(delivery_id: str, user: User, db: AsyncSession) -> GuideDelivery:
    delivery = await db.get(GuideDelivery, delivery_id)
    if delivery is None or str(delivery.recipient_id) != str(user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "delivery not found")
    return delivery


@router.get("/{delivery_id}")
async def get_delivery(
    delivery_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    delivery = await _own_delivery(delivery_id, current_user, db)
    return {
        "id": str(delivery.id),
        "session_id": str(delivery.session_id),
        "ciphertext": base64.b64encode(delivery.ciphertext).decode("ascii"),
    }


@router.delete("/{delivery_id}", status_code=status.HTTP_204_NO_CONTENT)
async def acknowledge_delivery(
    delivery_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    delivery = await _own_delivery(delivery_id, current_user, db)
    await db.delete(delivery)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
