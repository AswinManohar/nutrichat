"""Telegram bot linking.

Adds the `telegram_link` table that binds a Telegram `chat_id` to a
NutriChat `user_id`, written by the bot process after a `/link <code>`
command validates a short-lived Redis code.

Revision ID: 003
Revises: 002
Create Date: 2026-06-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_link",
        sa.Column("chat_id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            UUID(),
            sa.ForeignKey("user_goal.user_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.execute("ALTER TABLE telegram_link ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("telegram_link")
