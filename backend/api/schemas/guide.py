"""Pydantic schemas for session guides and step-by-step visual recall."""

from datetime import datetime
from pydantic import BaseModel, Field


class GuideStepResponse(BaseModel):
    """An individual step in a session how-to guide."""

    id: str
    step_number: int
    title: str = ""
    instruction: str
    image_url: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class GuideResponse(BaseModel):
    """A full session guide with summary and ordered steps."""

    id: str
    session_id: str | None = None
    user_id: str
    helper_id: str | None = None
    title: str
    summary: str = ""
    category: str = "general"
    steps_count: int = 0
    created_at: datetime
    updated_at: datetime
    steps: list[GuideStepResponse] = []

    model_config = {"from_attributes": True}


class GuideListResponse(BaseModel):
    """Summary representation of a guide for list screens."""

    id: str
    session_id: str | None = None
    title: str
    summary: str = ""
    category: str = "general"
    steps_count: int = 0
    thumbnail_url: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class GuideGenerateStepInput(BaseModel):
    """A single step provided during manual or assisted guide creation."""

    step_number: int
    title: str = ""
    instruction: str
    image_url: str | None = None


class GuideGenerateRequest(BaseModel):
    """Request payload to manually create or trigger AI generation of a guide."""

    session_id: str | None = None
    title: str
    summary: str = ""
    category: str = "general"
    steps: list[GuideGenerateStepInput] = Field(default_factory=list)
