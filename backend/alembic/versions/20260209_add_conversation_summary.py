"""Add conversation summary fields for long chat memory.

Revision ID: 20260209_summary
Revises:
Create Date: 2026-02-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260209_summary"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("conversation_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("conversation_summary_message_count", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "conversation_summary_message_count")
    op.drop_column("conversations", "conversation_summary")
