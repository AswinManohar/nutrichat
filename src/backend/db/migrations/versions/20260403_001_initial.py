"""Initial schema — 6 tables, 13 B-tree indexes, 2 IVFFlat pgvector indexes.

Revision ID: 001
Revises:
Create Date: 2026-04-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Extensions
    # ------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------------------------
    # user_goal
    # ------------------------------------------------------------------
    op.create_table(
        "user_goal",
        sa.Column("user_id", UUID(), primary_key=True),
        sa.Column("kcal_goal", sa.Float(), nullable=False),
        sa.Column("protein_goal", sa.Float(), nullable=False),
        sa.Column("fiber_goal", sa.Float(), nullable=False),
        sa.Column("dietary_prefs", JSONB(), nullable=False, server_default="{}"),
        sa.Column("streak_days", sa.Integer(), nullable=False, server_default="0"),
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
    )

    # ------------------------------------------------------------------
    # meal_log
    # ------------------------------------------------------------------
    op.create_table(
        "meal_log",
        sa.Column(
            "meal_id",
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
        sa.Column(
            "logged_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("meal_type", sa.String(20), nullable=False),
        sa.Column("kcal", sa.Float(), nullable=False),
        sa.Column("protein_g", sa.Float(), nullable=False),
        sa.Column("carbs_g", sa.Float(), nullable=False),
        sa.Column("fat_g", sa.Float(), nullable=False),
        sa.Column("fiber_g", sa.Float(), nullable=False),
        sa.Column("entities", JSONB(), nullable=False, server_default="[]"),
        sa.Column("embedding", sa.Text(), nullable=True),  # placeholder; altered below
        sa.Column("flags", JSONB(), nullable=False, server_default="{}"),
    )
    # Alter the placeholder column to the real vector type.
    # op.alter_column() does not support custom types, so we use raw DDL.
    op.execute("ALTER TABLE meal_log ALTER COLUMN embedding TYPE vector(768) USING NULL")

    # B-tree indexes
    op.create_index("ix_meal_log_user_logged_at", "meal_log", ["user_id", "logged_at"])
    op.create_index("ix_meal_log_user_protein", "meal_log", ["user_id", "protein_g"])
    op.create_index(
        "ix_meal_log_hybrid",
        "meal_log",
        ["user_id", "meal_type", "protein_g", "logged_at"],
    )

    # IVFFlat index — cosine similarity, 100 lists
    op.execute(
        """
        CREATE INDEX ix_meal_log_embedding
        ON meal_log
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
        """
    )

    # ------------------------------------------------------------------
    # user_memory
    # ------------------------------------------------------------------
    op.create_table(
        "user_memory",
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
        sa.Column("fact", sa.Text(), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.execute(
        "ALTER TABLE user_memory ALTER COLUMN embedding TYPE vector(768) USING NULL"
    )
    op.create_index("ix_user_memory_user_id", "user_memory", ["user_id"])
    op.execute(
        """
        CREATE INDEX ix_user_memory_embedding
        ON user_memory
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
        """
    )

    # ------------------------------------------------------------------
    # food_source
    # ------------------------------------------------------------------
    op.create_table(
        "food_source",
        sa.Column("fdc_id", sa.Integer(), primary_key=True),
        sa.Column("food_name", sa.String(255), nullable=False),
        sa.Column("nutrients", JSONB(), nullable=False, server_default="{}"),
        sa.Column("nutrients_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("data_quality", sa.String(50), nullable=True),
        sa.Column("source_db", sa.String(50), nullable=False, server_default="'FDC'"),
        sa.Column(
            "cached_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_food_source_food_name", "food_source", ["food_name"])

    # ------------------------------------------------------------------
    # daily_summary
    # ------------------------------------------------------------------
    op.create_table(
        "daily_summary",
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
        sa.Column("kcal", sa.Float(), nullable=False, server_default="0"),
        sa.Column("protein_g", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fiber_g", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "protein_goal_hit", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("has_veg_day", sa.Boolean(), nullable=False, server_default="false"),
        sa.UniqueConstraint("user_id", "date", name="uq_daily_summary_user_date"),
    )
    op.create_index("ix_daily_summary_user_date", "daily_summary", ["user_id", "date"])

    # ------------------------------------------------------------------
    # weekly_summary
    # ------------------------------------------------------------------
    op.create_table(
        "weekly_summary",
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
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("avg_protein_g", sa.Float(), nullable=False, server_default="0"),
        sa.Column("days_hit_protein", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "weak_spots", ARRAY(sa.String()), nullable=False, server_default="{}"
        ),
        sa.Column(
            "missed_meals", ARRAY(sa.String()), nullable=False, server_default="{}"
        ),
        sa.UniqueConstraint("user_id", "week_start", name="uq_weekly_summary_user_week"),
    )
    op.create_index(
        "ix_weekly_summary_user_week", "weekly_summary", ["user_id", "week_start"]
    )


def downgrade() -> None:
    op.drop_table("weekly_summary")
    op.drop_table("daily_summary")
    op.drop_table("food_source")
    op.drop_table("user_memory")
    op.drop_table("meal_log")
    op.drop_table("user_goal")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
    op.execute("DROP EXTENSION IF EXISTS vector")
