"""Daily Nutrient Check-up.

Adds the `nutrient_checkup` table: one row per user per day holding
rolling 7-day nutrient averages and trend vs the prior 7 days, written
nightly by the build_nutrient_checkup Celery task and read by
GET /nutrient-checkup.

Revision ID: 004
Revises: 003
Create Date: 2026-06-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nutrient_checkup",
        sa.Column(
            "id",
            UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(),
            sa.ForeignKey("user_goal.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("nutrients", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "date", name="uq_nutrient_checkup_user_date"),
    )
    op.create_index(
        "ix_nutrient_checkup_user_date", "nutrient_checkup", ["user_id", "date"]
    )
    # Row-level security policy (auth.uid() = user_id) is applied directly
    # against Supabase, which provides the `auth` schema. Plain Postgres
    # (local/test) lacks that schema, so only enable RLS here — matching
    # the telegram_link/integration_token migrations.
    op.execute("ALTER TABLE nutrient_checkup ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("nutrient_checkup")
