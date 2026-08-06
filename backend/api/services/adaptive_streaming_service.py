"""Adaptive Streaming & Bandwidth Optimization Service."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.session import Session
from models.session_participant import SessionParticipant


class AdaptiveStreamingService:
    """Handles dynamic resolution/bitrate scaling, FPS throttling, and RTT/packet-loss adaptation."""

    @staticmethod
    def _compute_auto_adaptation(rtt_ms: float, packet_loss: float) -> tuple[str, int, int]:
        """Compute optimal (resolution, bitrate_kbps, fps) based on RTT and packet loss."""
        if rtt_ms < 100.0 and packet_loss < 2.0:
            return ("1080p", 3000, 30)
        elif rtt_ms < 250.0 and packet_loss < 5.0:
            return ("720p", 1500, 30)
        elif rtt_ms < 500.0 and packet_loss < 15.0:
            return ("480p", 600, 15)
        else:
            return ("360p", 250, 10)

    @staticmethod
    async def adapt_stream(
        session_id: str,
        user_id: str,
        video_resolution: str | None,
        video_bitrate_kbps: int | None,
        video_fps: int | None,
        db: AsyncSession,
    ) -> SessionParticipant:
        """Manually update video streaming parameters."""
        result = await db.execute(
            select(SessionParticipant).where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.user_id == user_id,
            )
        )
        participant = result.scalar_one_or_none()

        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Participant not found in session",
            )

        if video_resolution is not None:
            participant.video_resolution = video_resolution
        if video_bitrate_kbps is not None:
            participant.video_bitrate_kbps = video_bitrate_kbps
        if video_fps is not None:
            participant.video_fps = video_fps

        await db.commit()
        await db.refresh(participant)
        return participant

    @staticmethod
    async def process_network_metrics(
        session_id: str,
        user_id: str,
        rtt_ms: float,
        jitter_ms: float | None,
        packet_loss_percent: float,
        available_bandwidth_kbps: int | None,
        db: AsyncSession,
    ) -> tuple[SessionParticipant, bool]:
        """Process client network metrics and auto-adapt video streaming parameters if needed."""
        result = await db.execute(
            select(SessionParticipant).where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.user_id == user_id,
            )
        )
        participant = result.scalar_one_or_none()

        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Participant not found in session",
            )

        participant.rtt_ms = rtt_ms
        participant.packet_loss_percent = packet_loss_percent

        res, bitrate, fps = AdaptiveStreamingService._compute_auto_adaptation(
            rtt_ms=rtt_ms, packet_loss=packet_loss_percent
        )

        auto_adapted = (
            participant.video_resolution != res
            or participant.video_bitrate_kbps != bitrate
            or participant.video_fps != fps
        )

        participant.video_resolution = res
        participant.video_bitrate_kbps = bitrate
        participant.video_fps = fps

        await db.commit()
        await db.refresh(participant)
        return participant, auto_adapted

    @staticmethod
    async def get_stream_config(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> SessionParticipant:
        """Get current streaming configuration for participant."""
        result = await db.execute(
            select(SessionParticipant).where(
                SessionParticipant.session_id == session_id,
                SessionParticipant.user_id == user_id,
            )
        )
        participant = result.scalar_one_or_none()

        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Participant not found in session",
            )

        return participant
