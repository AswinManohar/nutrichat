"""Add meal_log.micros — the meal-level micronutrient summary (spec 008).

One JSONB object per logged meal: ``{key: {"total", "est", "known"}}`` for
every tracked nutrient with at least one known value (data-model.md §3). An
absent key means unknown. This is the only stored micronutrient data on a
logged meal (FR-014a/FR-018). No backfill: existing rows get ``{}``
(FR-012).

Revision ID: 018_meal_micros
Revises: 017_rls_new_tables
Create Date: 2026-10-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "018_meal_micros"
down_revision = "017_rls_new_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meal_log",
        sa.Column(
            "micros",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("meal_log", "micros")
