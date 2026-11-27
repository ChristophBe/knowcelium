"""keep what was searched for an answer

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("search_steps", JSONB, nullable=False, server_default="[]"),
        schema="chat",
    )


def downgrade() -> None:
    op.drop_column("messages", "search_steps", schema="chat")
