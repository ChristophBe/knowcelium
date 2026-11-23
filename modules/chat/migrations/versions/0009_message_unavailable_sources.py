"""keep which live sources did not answer for an answer

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("unavailable_sources", JSONB, nullable=False, server_default="[]"),
        schema="chat",
    )


def downgrade() -> None:
    op.drop_column("messages", "unavailable_sources", schema="chat")
