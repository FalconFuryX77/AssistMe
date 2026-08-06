"""Pydantic schemas for Phase 11 In-App Chat & Chunked File Transfer."""

from datetime import datetime
from pydantic import BaseModel, field_validator


class ChatMessageSendRequest(BaseModel):
    """Request body for sending an in-app chat message."""

    content: str
    is_encrypted: bool = False
    encrypted_payload: str | None = None

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if not v or len(v.strip()) == 0:
            raise ValueError("Chat message content cannot be empty")
        return v


class ChatMessageResponse(BaseModel):
    """Full chat message representation."""

    id: str
    session_id: str
    sender_id: str
    content: str
    is_encrypted: bool = False
    encrypted_payload: str | None = None
    timestamp: datetime

    model_config = {"from_attributes": True}


class ChatMessageListResponse(BaseModel):
    """Response wrapper for list of session chat messages."""

    session_id: str
    total_messages: int
    messages: list[ChatMessageResponse]


class FileTransferInitiateRequest(BaseModel):
    """Request body for initiating a chunked file transfer."""

    filename: str
    file_size_bytes: int
    mime_type: str = "application/octet-stream"
    checksum_sha256: str
    total_chunks: int = 1

    @field_validator("file_size_bytes")
    @classmethod
    def validate_size(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("file_size_bytes must be greater than 0")
        return v

    @field_validator("checksum_sha256")
    @classmethod
    def validate_checksum(cls, v: str) -> str:
        if len(v) != 64:
            raise ValueError("checksum_sha256 must be a 64-character hex string")
        return v.lower()


class FileChunkUploadRequest(BaseModel):
    """Request body for uploading an individual file chunk."""

    chunk_index: int
    chunk_data_base64: str
    chunk_checksum: str | None = None


class FileTransferResponse(BaseModel):
    """Representation of a file transfer session."""

    id: str
    session_id: str
    sender_id: str
    filename: str
    file_size_bytes: int
    mime_type: str
    checksum_sha256: str
    status: str
    total_chunks: int
    received_chunks: int
    download_url: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class FileTransferListResponse(BaseModel):
    """Response wrapper for list of session file transfers."""

    session_id: str
    total_transfers: int
    transfers: list[FileTransferResponse]
