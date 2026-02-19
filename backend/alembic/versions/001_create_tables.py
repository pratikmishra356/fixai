"""Create all tables: organizations, conversations, messages.

Revision ID: 001
Revises:
Create Date: 2026-02-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("code_parser_base_url", sa.String(512), nullable=True),
        sa.Column("code_parser_org_id", sa.String(128), nullable=True),
        sa.Column("code_parser_repo_id", sa.String(128), nullable=True),
        sa.Column("metrics_explorer_base_url", sa.String(512), nullable=True),
        sa.Column("metrics_explorer_org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("logs_explorer_base_url", sa.String(512), nullable=True),
        sa.Column("logs_explorer_org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("claude_api_key", sa.Text(), nullable=True),
        sa.Column("claude_bedrock_url", sa.String(512), nullable=True),
        sa.Column("claude_model_id", sa.String(200), nullable=True),
        sa.Column("claude_max_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(512), nullable=False, server_default="New Conversation"),
        sa.Column("conversation_summary", sa.Text(), nullable=True),
        sa.Column("conversation_summary_message_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_organization_id", "conversations", ["organization_id"])

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("context", postgresql.JSON(), nullable=True),
        sa.Column("tool_name", sa.String(100), nullable=True),
        sa.Column("tool_call_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("organizations")
