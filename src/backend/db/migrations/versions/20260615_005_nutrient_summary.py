"""Daily Nutrient Summary vs RDA Baseline.

Adds notable_nutrients/summary_text (generated nightly alongside the existing
nutrient_checkup aggregates) and telegram_sent_at/chat_nudge_seen_at
(delivery-tracking for the Telegram push and chat nudge) to nutrient_checkup.

Revision ID: 005
Revises: 004
Create Date: 2026-06-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nutrient_checkup",
        sa.Column(
            "notable_nutrients", JSONB(), nullable=False, server_default="[]"
        ),
    )
    op.add_column(
        "nutrient_checkup",
        sa.Column("summary_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "nutrient_checkup",
        sa.Column("telegram_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "nutrient_checkup",
        sa.Column("chat_nudge_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("nutrient_checkup", "chat_nudge_seen_at")
    op.drop_column("nutrient_checkup", "telegram_sent_at")
    op.drop_column("nutrient_checkup", "summary_text")
    op.drop_column("nutrient_checkup", "notable_nutrients")
