"""In-App Chat Messaging & Chunked File Transfer Service."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.chat_message import ChatMessage
from models.file_transfer import FileTransfer
from models.session import Session


class ChatFileService:
    """Manages session text chat messages, E2EE chat payloads, and chunked file transfer signaling."""

    @staticmethod
    async def send_chat_message(
        session_id: str,
        sender_id: str,
        content: str,
        is_encrypted: bool,
        encrypted_payload: str | None,
        db: AsyncSession,
    ) -> ChatMessage:
        """Send an in-app text chat message in a session."""
        result = await db.execute(
            select(Session)
            .where(Session.id == session_id)
            .options(selectinload(Session.participants))
        )
        session = result.scalar_one_or_none()

        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )

        participant = next(
            (p for p in session.participants if p.user_id == sender_id), None
        )
        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a participant of this session",
            )

        msg = ChatMessage(
            session_id=session.id,
            sender_id=sender_id,
            content=content,
            is_encrypted=is_encrypted,
            encrypted_payload=encrypted_payload,
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        return msg

    @staticmethod
    async def list_chat_messages(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> dict:
        """Retrieve all chat messages for a session."""
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.timestamp.asc())
        )
        messages = result.scalars().all()

        return {
            "session_id": session_id,
            "total_messages": len(messages),
            "messages": messages,
        }

    @staticmethod
    async def initiate_file_transfer(
        session_id: str,
        sender_id: str,
        filename: str,
        file_size_bytes: int,
        mime_type: str,
        checksum_sha256: str,
        total_chunks: int,
        db: AsyncSession,
    ) -> FileTransfer:
        """Register a new chunked file transfer in a session."""
        result = await db.execute(
            select(Session)
            .where(Session.id == session_id)
            .options(selectinload(Session.participants))
        )
        session = result.scalar_one_or_none()

        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )

        participant = next(
            (p for p in session.participants if p.user_id == sender_id), None
        )
        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a participant of this session",
            )

        transfer = FileTransfer(
            session_id=session.id,
            sender_id=sender_id,
            filename=filename,
            file_size_bytes=file_size_bytes,
            mime_type=mime_type,
            checksum_sha256=checksum_sha256,
            total_chunks=total_chunks,
            status="initiating",
        )
        db.add(transfer)
        await db.commit()
        await db.refresh(transfer)
        return transfer

    @staticmethod
    async def upload_file_chunk(
        session_id: str,
        file_transfer_id: str,
        user_id: str,
        chunk_index: int,
        chunk_data_base64: str,
        chunk_checksum: str | None,
        db: AsyncSession,
    ) -> FileTransfer:
        """Process and increment chunk upload progress for a file transfer."""
        result = await db.execute(
            select(FileTransfer).where(
                FileTransfer.id == file_transfer_id,
                FileTransfer.session_id == session_id,
            )
        )
        transfer = result.scalar_one_or_none()

        if transfer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File transfer not found",
            )

        if transfer.status == "failed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File transfer has failed and cannot accept new chunks",
            )

        transfer.status = "transferring"
        transfer.received_chunks = min(transfer.received_chunks + 1, transfer.total_chunks)

        await db.commit()
        await db.refresh(transfer)
        return transfer

    @staticmethod
    async def complete_file_transfer(
        session_id: str,
        file_transfer_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> FileTransfer:
        """Finalize file transfer and mark status as completed with download URL."""
        result = await db.execute(
            select(FileTransfer).where(
                FileTransfer.id == file_transfer_id,
                FileTransfer.session_id == session_id,
            )
        )
        transfer = result.scalar_one_or_none()

        if transfer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File transfer not found",
            )

        transfer.status = "completed"
        transfer.received_chunks = transfer.total_chunks
        transfer.download_url = f"https://storage.assistme.internal/transfers/{transfer.id}/{transfer.filename}"

        await db.commit()
        await db.refresh(transfer)
        return transfer

    @staticmethod
    async def list_file_transfers(
        session_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> dict:
        """Retrieve all file transfers for a session."""
        result = await db.execute(
            select(FileTransfer)
            .where(FileTransfer.session_id == session_id)
            .order_by(FileTransfer.created_at.desc())
        )
        transfers = result.scalars().all()

        return {
            "session_id": session_id,
            "total_transfers": len(transfers),
            "transfers": transfers,
        }
