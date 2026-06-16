"""Mindful Eating mode — tracking_mode column + nullable goals.

Adds user_goal.tracking_mode ('goals' | 'mindful', default 'goals') and makes
the three goal columns nullable so a mindful-mode user can have null targets.
Existing rows default to 'goals' and are unaffected.

Revision ID: 006
Revises: 005
Create Date: 2026-06-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_goal",
        sa.Column(
            "tracking_mode",
            sa.Text(),
            nullable=False,
            server_default="goals",
        ),
    )
    op.create_check_constraint(
        "user_goal_tracking_mode_check",
        "user_goal",
        "tracking_mode IN ('goals', 'mindful')",
    )
    op.alter_column("user_goal", "kcal_goal", nullable=True)
    op.alter_column("user_goal", "protein_goal", nullable=True)
    op.alter_column("user_goal", "fiber_goal", nullable=True)


def downgrade() -> None:
    op.alter_column("user_goal", "fiber_goal", nullable=False)
    op.alter_column("user_goal", "protein_goal", nullable=False)
    op.alter_column("user_goal", "kcal_goal", nullable=False)
    op.drop_constraint("user_goal_tracking_mode_check", "user_goal", type_="check")
    op.drop_column("user_goal", "tracking_mode")
