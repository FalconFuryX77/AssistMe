"""Pydantic schemas for Phase 11 Intelligent Assistance.

Covers: learning repeated tasks, context-aware assistance suggestions, and
per-user preferred assistance mode memory.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

VALID_ACTIONS = ("remote_control", "screen_share", "voice", "pointer", "drawing", "chat")
VALID_MODES = ("voice", "pointer", "drawing", "tap", "restricted")


class TaskRecordRequest(BaseModel):
    """Client-reported assistance task occurrence for learning."""

    foreground_app: str | None = None
    platform: str | None = None
    action: str  # e.g. "remote_control", "screen_share", "voice", "chat"

    #: Whether the action resolved the helpee's problem.
    #:
    #: The single most important addition to this schema. Without an outcome
    #: the engine can only learn what was *tried*, so an action a helper
    #: retried five times because it kept failing outranks one that worked
    #: immediately. Defaults to True so existing clients keep working; a client
    #: that reports honestly gets materially better suggestions.
    succeeded: bool = True

    #: The action taken immediately before this one, for the transition model.
    #: ``None`` means this is the first action of the session.
    previous_action: str | None = None

    @field_validator("previous_action")
    @classmethod
    def validate_previous_action(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v_lower = v.lower()
        if v_lower not in VALID_ACTIONS:
            raise ValueError(f"previous_action must be one of {VALID_ACTIONS}")
        return v_lower

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        v_lower = v.lower()
        if v_lower not in VALID_ACTIONS:
            raise ValueError(f"action must be one of {VALID_ACTIONS}")
        return v_lower

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str | None) -> str | None:
        if v is not None and v.lower() not in ("android", "ios", "web", "unknown"):
            raise ValueError("platform must be 'android', 'ios', 'web', or 'unknown'")
        return v.lower() if v else v


class TaskPatternResponse(BaseModel):
    """A learned repeated-task pattern."""

    id: str
    context_signature: str
    foreground_app: str | None = None
    platform: str | None = None
    action: str
    occurrence_count: int
    last_occurred_at: datetime

    #: How many of those occurrences resolved the problem.
    success_count: int = 0
    #: Exponentially time-decayed exposure and reward. Ranking uses these
    #: rather than the raw counts, so abandoned habits fade out.
    decayed_count: float = 0.0
    decayed_success: float = 0.0
    first_occurred_at: datetime | None = None

    model_config = {"from_attributes": True}


class PreferredModeResponse(BaseModel):
    """Per-user preferred assistance mode."""

    user_id: str
    mode: str
    updated_at: datetime

    #: ``"explicit"`` when the user chose it, ``"inferred"`` when derived from
    #: behaviour. The policy engine respects a stated preference up to the
    #: safety ceiling but treats an inferred one as advisory.
    source: str = "explicit"
    confidence: float = 1.0
    observation_count: int = 0

    model_config = {"from_attributes": True}


class PreferredModeRequest(BaseModel):
    """Request body to set the user's preferred assistance mode."""

    mode: str

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        v_lower = v.lower()
        if v_lower not in VALID_MODES:
            raise ValueError(f"mode must be one of {VALID_MODES}")
        return v_lower


class AssistanceSuggestionResponse(BaseModel):
    """A context-aware assistance suggestion."""

    id: str
    session_id: str
    suggestion_type: str  # "repeated_task", "context_help", "preferred_mode"
    title: str
    detail: str | None = None
    confidence: float = 0.0
    created_at: datetime

    #: The concrete action suggested, so acceptance can be attributed to an
    #: action rather than only to a headline string.
    action: str | None = None
    #: Position in the returned list, for rank-aware metrics from production.
    rank: int = 1

    model_config = {"from_attributes": True}


class SuggestionsResponse(BaseModel):
    """Wrapper for a set of assistance suggestions."""

    session_id: str
    total_suggestions: int
    suggestions: list[AssistanceSuggestionResponse]


class TaskPatternListResponse(BaseModel):
    """Wrapper for a user's learned task patterns."""

    user_id: str
    total_patterns: int
    patterns: list[TaskPatternResponse]