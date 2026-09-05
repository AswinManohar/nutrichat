"""device_token — FCM registration tokens for Android push notifications.

One row per registered device token. A token can move between users (device
re-registers under a new logged-in account) so registration upserts on the
unique token rather than inserting a duplicate row.

Revision ID: 013
Revises: 012
Create Date: 2026-09-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_token",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("user_goal.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "platform", sa.String(16), nullable=False, server_default="fcm"
        ),
        sa.Column("token", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_device_token_user", "device_token", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_device_token_user", table_name="device_token")
    op.drop_table("device_token")
