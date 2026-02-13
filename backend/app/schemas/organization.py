"""Organization Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class OrganizationCreate(BaseModel):
    """Request to create an organization."""
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(
        ..., min_length=1, max_length=255, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )
    description: str | None = None

    # Code Parser (ULID strings)
    code_parser_base_url: str | None = None
    code_parser_org_id: str | None = None
    code_parser_repo_id: str | None = None

    # Metrics Explorer (UUID)
    metrics_explorer_base_url: str | None = None
    metrics_explorer_org_id: UUID | None = None

    # Logs Explorer (UUID)
    logs_explorer_base_url: str | None = None
    logs_explorer_org_id: UUID | None = None


class OrganizationUpdate(BaseModel):
    """Request to update an organization."""
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None

    code_parser_base_url: str | None = None
    code_parser_org_id: str | None = None
    code_parser_repo_id: str | None = None

    metrics_explorer_base_url: str | None = None
    metrics_explorer_org_id: UUID | None = None

    logs_explorer_base_url: str | None = None
    logs_explorer_org_id: UUID | None = None

    # AI / LLM config
    claude_api_key: str | None = None
    claude_bedrock_url: str | None = None
    claude_model_id: str | None = None
    claude_max_tokens: int | None = None


class AIConfigUpdate(BaseModel):
    """Dedicated request to update AI config on an org."""
    claude_api_key: str | None = None
    claude_bedrock_url: str | None = None
    claude_model_id: str | None = None
    claude_max_tokens: int | None = None


class OrganizationResponse(BaseModel):
    """Organization response."""
    id: UUID
    name: str
    slug: str
    description: str | None = None
    is_active: bool

    code_parser_base_url: str | None = None
    code_parser_org_id: str | None = None
    code_parser_repo_id: str | None = None

    metrics_explorer_base_url: str | None = None
    metrics_explorer_org_id: UUID | None = None

    logs_explorer_base_url: str | None = None
    logs_explorer_org_id: UUID | None = None

    # AI config
    claude_api_key_set: bool = False
    claude_bedrock_url: str | None = None
    claude_model_id: str | None = None
    claude_max_tokens: int | None = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
