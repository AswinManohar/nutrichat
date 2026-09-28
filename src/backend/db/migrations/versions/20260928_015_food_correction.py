"""food_correction — records of a user's manual USDA match corrections.

One row per corrected item logged via POST /meals/log-items (spec 003,
"Correct a Wrong Food Match", #39). Write-only for this feature: nothing
reads this table to influence future matching (FR-012).

NOTE: `andorid_prod` has its own, different revision `014` (coaching
feedback), branching from the same `013`. This migration also branches
from `013`, so the two branches will need an Alembic merge revision when
`feat/android-app` joins `andorid_prod` (research R6, tracked separately).

Revision ID: 015_food_correction
Revises: 013
Create Date: 2026-09-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "015_food_correction"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "food_correction",
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
            "meal_log_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("meal_log.meal_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_phrase", sa.Text(), nullable=False),
        sa.Column("from_fdc_id", sa.Integer(), nullable=True),
        sa.Column("from_name", sa.Text(), nullable=False),
        sa.Column("to_fdc_id", sa.Integer(), nullable=False),
        sa.Column("to_name", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "method IN ('suggestion', 'search')",
            name="ck_food_correction_method",
        ),
    )
    op.create_index("ix_food_correction_user_id", "food_correction", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_food_correction_user_id", table_name="food_correction")
    op.drop_table("food_correction")
