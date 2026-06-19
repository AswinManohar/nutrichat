"""My Meals — saved per-user composite meals.

Adds `user_meal`: a saved meal = a name + a list of resolved ingredients
(same JSONB shape as meal_log.entities) + denormalized macro totals + an
optional embedding for later semantic match. RLS mirrors the other per-user
tables (auth.uid() = user_id).

Revision ID: 007
Revises: 006
Create Date: 2026-06-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_meal",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=False),
            sa.ForeignKey("user_goal.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_normalized", sa.Text(), nullable=False),
        sa.Column("ingredients", JSONB(), nullable=False, server_default="[]"),
        sa.Column("kcal", sa.Float(), nullable=False),
        sa.Column("protein_g", sa.Float(), nullable=False),
        sa.Column("carbs_g", sa.Float(), nullable=False),
        sa.Column("fat_g", sa.Float(), nullable=False),
        sa.Column("fiber_g", sa.Float(), nullable=False),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # One active saved meal per (user, normalized name).
    op.create_index(
        "ix_user_meal_user_normalized",
        "user_meal",
        ["user_id", "name_normalized"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    # RLS — per-user isolation, matching the other tables.
    op.execute("ALTER TABLE user_meal ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY user_meal_owner ON user_meal "
        "USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS user_meal_owner ON user_meal")
    op.drop_index("ix_user_meal_user_normalized", table_name="user_meal")
    op.drop_table("user_meal")
