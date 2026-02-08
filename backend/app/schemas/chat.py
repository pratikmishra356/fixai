"""Chat / conversation Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class UserContext(BaseModel):
    """Optional context the user provides with a message."""
    service: str | None = Field(None, description="Service name to investigate")
    environment: str | None = Field(None, description="Environment (prod, staging, etc.)")
    file_path: str | None = Field(None, description="Specific file path to look at")


class MessageCreate(BaseModel):
    """Request to send a message in a conversation."""
    content: str = Field(..., min_length=1, max_length=10000)
    context: UserContext | None = None


class MessageResponse(BaseModel):
    """Single message response."""
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    context: dict | None = None
    tool_name: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationCreate(BaseModel):
    """Request to create a conversation."""
    title: str = Field(default="New Conversation", max_length=512)


class ConversationResponse(BaseModel):
    """Conversation summary response."""
    id: UUID
    organization_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    model_config = {"from_attributes": True}


class ConversationDetailResponse(BaseModel):
    """Conversation with all messages."""
    id: UUID
    organization_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse] = []

    model_config = {"from_attributes": True}


class StreamEvent(BaseModel):
    """Server-Sent Event payload."""
    event: str  # "token", "tool_start", "tool_end", "error", "done"
    data: str
