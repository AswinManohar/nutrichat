"""Onboarding implementation-intentions: first_meal_time + push_subscription.

Adds user_goal.first_meal_time (the user's typical first-meal time, captured
during onboarding as a behavioral implementation intention) and a
push_subscription table holding Web Push subscriptions. The recurring sender
that reads these is intentionally out of scope for this migration.

Existing user_goal rows receive NULL first_meal_time — no backfill required.

Revision ID: 010
Revises: 009
Create Date: 2026-06-21
"""

from __future__ import annotations

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE user_goal ADD COLUMN IF NOT EXISTS first_meal_time TEXT"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS push_subscription (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL,
            endpoint TEXT NOT NULL UNIQUE,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_push_subscription_user_id "
        "ON push_subscription (user_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS push_subscription")
    op.execute("ALTER TABLE user_goal DROP COLUMN IF EXISTS first_meal_time")
