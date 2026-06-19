"""meal_log.label — persist dish name(s) for history retrieval.

Decomposed composite dishes are logged as normal meal_log rows whose entities
are the ingredients (so "biryani" is no longer in the row). `label` snapshots
the human-facing dish name(s) at log time so "how often did I have biryani" is
a one-column lookup. Nullable; older rows stay NULL.

Revision ID: 008
Revises: 007
Create Date: 2026-06-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meal_log", sa.Column("label", sa.Text(), nullable=True))
    op.create_index(
        "ix_meal_log_user_label", "meal_log", ["user_id", "label"]
    )


def downgrade() -> None:
    op.drop_index("ix_meal_log_user_label", table_name="meal_log")
    op.drop_column("meal_log", "label")
