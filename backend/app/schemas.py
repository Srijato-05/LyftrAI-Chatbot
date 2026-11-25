"""Pydantic request and response schemas matching the API contract."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator


class HealthResponse(BaseModel):
    """Response schema for GET /health."""

    status: Literal["ok"]
    keys_configured: int
    cache_enabled: bool


class ChatRequest(BaseModel):
    """Request payload for POST /chat."""

    model_config = ConfigDict(extra="ignore")

    session_id: str
    message: str
    system_prompt: str | None = None

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        """Enforce 1-128 chars without stripping so echoed session_id matches exactly."""
        if not value or not value.strip():
            raise ValueError("session_id must not be empty")
        if len(value) > 128:
            raise ValueError("session_id must be at most 128 characters")
        return value

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        """Trim whitespace, then enforce 1-4000 chars."""
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("message must not be empty")
        if len(trimmed) > 4000:
            raise ValueError("message must be at most 4000 characters")
        return trimmed

    @field_validator("system_prompt")
    @classmethod
    def normalize_system_prompt(cls, value: str | None) -> str | None:
        """Trim optional system prompt and convert empty strings to None."""
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class ChatMetadata(BaseModel):
    """Per-request metadata returned with each assistant reply."""

    resolution_source: Literal["LIVE_INFERENCE", "LLM_CACHE"]
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int


class ChatResponse(BaseModel):
    """Response schema for POST /chat."""

    session_id: str
    reply: str
    metadata: ChatMetadata


class HistoryMessage(BaseModel):
    """Single stored message in GET /sessions/{session_id}/messages."""

    role: Literal["user", "assistant"]
    content: str
    metadata: dict[str, Any] | None = None


class HistoryResponse(BaseModel):
    """Response schema for GET /sessions/{session_id}/messages."""

    session_id: str
    messages: list[HistoryMessage]

