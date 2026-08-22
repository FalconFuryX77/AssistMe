"""Assistance request & escalation business logic (security-focused flow).

Security invariants enforced here:
  1. A helper may only assist if their device is on the helpee's trusted list.
  2. Acceptance grants ONLY overlay-drawing by default (least privilege).
  3. Escalation to interactive control requires the helpee to explicitly
     accept the stated risks (disclaimer) before any capability is granted.
"""

import json
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.assistance_request import VALID_CAPABILITIES
from models.assistance_request import AssistanceEscalation, AssistanceRequest
from models.session import Session
from models.session_participant import SessionParticipant
from models.trusted_device import TrustedDevice

# The default capability granted on accepting a help request (overlay only).
DEFAULT_GRANTED_CAPABILITIES = ("overlay_draw",)


class AssistanceRequestService:
    """Manages the one-click help request and escalation flow."""

    # ------------------------------------------------------------------
    # Help request (helpee → helper)
    # ------------------------------------------------------------------

    @staticmethod
    async def request_help(
        session_id: str,
        helpee_user_id: str,
        helper_user_id: str,
        helper_device_fingerprint: str,
        db: AsyncSession,
    ) -> AssistanceRequest:
        """A helpee requests help from a helper on their trusted device.

        Raises:
            403 – helper's device is not trusted by the helpee
            409 – there is already a pending request for this session
        """
        session = await AssistanceRequestService._load_session(session_id, db)
        await AssistanceRequestService._ensure_participant(session, helpee_user_id, "helpee", db)

        # The helper must be a participant too.
        await AssistanceRequestService._ensure_participant(session, helper_user_id, None, db)

        # Enforce: the helper's device MUST be trusted by the helpee.
        trusted = await AssistanceRequestService._is_device_trusted(
            helpee_user_id, helper_device_fingerprint, db
        )
        if not trusted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Helper device is not in the trusted device list",
            )

        # No duplicate pending requests.
        result = await db.execute(
            select(AssistanceRequest).where(
                AssistanceRequest.session_id == session_id,
                AssistanceRequest.status == "pending",
            )
        )
        if result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A help request is already pending for this session",
            )

        request = AssistanceRequest(
            session_id=session_id,
            helpee_user_id=helpee_user_id,
            helper_user_id=helper_user_id,
            helper_device_fingerprint=helper_device_fingerprint,
            status="pending",
            initial_capabilities=json.dumps(list(DEFAULT_GRANTED_CAPABILITIES)),
        )
        db.add(request)
        await db.commit()
        await db.refresh(request)
        return request

    @staticmethod
    async def respond_to_request(
        request_id: str,
        helper_user_id: str,
        accept: bool,
        helper_device_fingerprint: str | None,
        db: AsyncSession,
    ) -> AssistanceRequest:
        """The helper accepts or denies a pending assistance request.

        Acceptance grants only the default overlay-drawing capability.
        """
        result = await db.execute(
            select(AssistanceRequest).where(AssistanceRequest.id == request_id)
        )
        request = result.scalar_one_or_none()
        if request is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Assistance request not found",
            )

        if request.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Assistance request already responded to",
            )

        if request.helper_user_id != helper_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not the intended helper for this request",
            )

        # If accepting, re-verify the helper's device is still trusted.
        if accept and helper_device_fingerprint:
            trusted = await AssistanceRequestService._is_device_trusted(
                request.helpee_user_id, helper_device_fingerprint, db
            )
            if not trusted:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Helper device is no longer trusted",
                )

        request.status = "accepted" if accept else "denied"
        request.responded_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(request)
        return request

    # ------------------------------------------------------------------
    # Escalation (helper requests more control)
    # ------------------------------------------------------------------

    @staticmethod
    async def request_escalation(
        session_id: str,
        helper_user_id: str,
        target_capabilities: list[str],
        db: AsyncSession,
    ) -> AssistanceEscalation:
        """A helper requests more control than overlay-only.

        Generates a human-readable risk disclaimer that the helpee must accept.
        No capability is granted until the helpee explicitly accepts.
        """
        session = await AssistanceRequestService._load_session(session_id, db)
        await AssistanceRequestService._ensure_participant(session, helper_user_id, "helper", db)

        # Find the helpee's active (accepted) request.
        result = await db.execute(
            select(AssistanceRequest).where(
                AssistanceRequest.session_id == session_id,
                AssistanceRequest.status == "accepted",
            )
        )
        request = result.scalar_one_or_none()

        target = list(dict.fromkeys(c.lower() for c in target_capabilities))
        target = [c for c in target if c in VALID_CAPABILITIES]

        disclaimer = AssistanceRequestService._build_disclaimer(target)

        escalation = AssistanceEscalation(
            session_id=session_id,
            request_id=request.id if request else None,
            requested_by_user_id=helper_user_id,
            target_capabilities=json.dumps(target),
            status="pending",
            disclaimer_text=disclaimer,
            disclaimer_accepted=False,
        )
        db.add(escalation)
        await db.commit()
        await db.refresh(escalation)
        return escalation

    @staticmethod
    async def respond_to_escalation(
        escalation_id: str,
        helpee_user_id: str,
        accept: bool,
        accept_disclaimer: bool,
        db: AsyncSession,
    ) -> AssistanceEscalation:
        """The helpee responds to an escalation request.

        Interactive control is ONLY granted when the helpee both accepts AND
        explicitly accepts the stated risks (disclaimer).
        """
        result = await db.execute(
            select(AssistanceEscalation).where(AssistanceEscalation.id == escalation_id)
        )
        escalation = result.scalar_one_or_none()
        if escalation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Escalation not found",
            )

        if escalation.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Escalation already responded to",
            )

        # Verify the responding user is the helpee of the session.
        session = await AssistanceRequestService._load_session(escalation.session_id, db)
        await AssistanceRequestService._ensure_participant(session, helpee_user_id, "helpee", db)

        escalation.status = "approved" if accept else "rejected"
        escalation.responded_at = datetime.now(timezone.utc)

        if accept:
            # Interactive control requires explicit disclaimer acceptance.
            if not accept_disclaimer:
                escalation.status = "rejected"
                await db.commit()
                await db.refresh(escalation)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Risks were not accepted — control not granted",
                )
            escalation.disclaimer_accepted = True
            escalation.granted_capabilities = escalation.target_capabilities

        await db.commit()
        await db.refresh(escalation)
        return escalation

    @staticmethod
    async def get_escalation(escalation_id: str, db: AsyncSession) -> AssistanceEscalation:
        """Fetch an escalation (e.g. to display its disclaimer)."""
        result = await db.execute(
            select(AssistanceEscalation).where(AssistanceEscalation.id == escalation_id)
        )
        escalation = result.scalar_one_or_none()
        if escalation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Escalation not found",
            )
        return escalation

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_disclaimer(target: list[str]) -> str:
        """Generate a clear, human-readable disclaimer of what is being granted."""
        lines = [
            "You are about to allow the helper to:",
        ]
        if "tap" in target or "drag" in target:
            lines.append(
                "  • Control your device (tap and drag on your screen as if by you)."
            )
        if "tap" in target:
            lines.append(
                "  • This may interact with apps, buttons, and fields on your device."
            )
        if "drag" in target:
            lines.append("  • Drag content and scroll through your screen.")
        if "pointer" in target:
            lines.append("  • Move a pointer/annotations over your screen (non-destructive).")
        if "overlay_draw" in target:
            lines.append("  • Draw on an overlay layer above your screen (safe, reversible).")
        if "voice" in target:
            lines.append("  • Speak to you through the audio channel.")
        lines += [
            "",
            "Risks:",
            "  • The helper could perform actions you did not intend.",
            "  • Avoid granting control while banking, passwords, or sensitive data are visible.",
            "  • You can revoke control at any time from your device.",
        ]
        return "\n".join(lines)

    @staticmethod
    async def _load_session(session_id: str, db: AsyncSession) -> Session:
        result = await db.execute(select(Session).where(Session.id == session_id))
        session = result.scalar_one_or_none()
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )
        return session

    @staticmethod
    async def _ensure_participant(
        session: Session,
        user_id: str,
        expected_role: str | None,
        db: AsyncSession,
    ) -> SessionParticipant:
        result = await db.execute(
            select(SessionParticipant).where(
                SessionParticipant.session_id == session.id,
                SessionParticipant.user_id == user_id,
            )
        )
        participant = result.scalar_one_or_none()
        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a participant of this session",
            )
        if expected_role and participant.role != expected_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User is not a {expected_role} in this session",
            )
        return participant

    @staticmethod
    async def _is_device_trusted(
        owner_user_id: str,
        device_fingerprint: str,
        db: AsyncSession,
    ) -> bool:
        result = await db.execute(
            select(TrustedDevice).where(
                TrustedDevice.owner_user_id == owner_user_id,
                TrustedDevice.device_fingerprint == device_fingerprint,
                TrustedDevice.status == "accepted",
            )
        )
        return result.scalar_one_or_none() is not None
