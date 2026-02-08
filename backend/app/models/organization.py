"""Organization model with service mappings."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # --- Code Parser service mapping ---
    # Both org_id and repo_id are Strings because code-parser uses ULID-style IDs
    code_parser_base_url = Column(String(512), nullable=True)
    code_parser_org_id = Column(String(128), nullable=True)
    code_parser_repo_id = Column(String(128), nullable=True)

    # --- Metrics Explorer service mapping ---
    metrics_explorer_base_url = Column(String(512), nullable=True)
    metrics_explorer_org_id = Column(UUID(as_uuid=True), nullable=True)

    # --- Logs Explorer service mapping ---
    logs_explorer_base_url = Column(String(512), nullable=True)
    logs_explorer_org_id = Column(UUID(as_uuid=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    conversations = relationship(
        "Conversation", back_populates="organization", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Organization {self.slug}>"
