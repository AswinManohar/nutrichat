"""Read-only integration API support — soft delete, cursors, tokens.

Adds `updated_at`/`deleted_at` to meal_log, `updated_at` to daily_summary and
weekly_summary, moddatetime triggers to keep them current, cursor indexes for
keyset pagination, and a new `integration_token` table for service-token auth.

Revision ID: 002
Revises: 001
Create Date: 2026-06-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Extensions
    # ------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS moddatetime")

    # ------------------------------------------------------------------
    # meal_log — updated_at, deleted_at
    # ------------------------------------------------------------------
    op.add_column(
        "meal_log",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "meal_log",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE meal_log SET updated_at = logged_at")

    op.execute("""
        CREATE TRIGGER meal_log_set_updated_at
        BEFORE UPDATE ON meal_log
        FOR EACH ROW
        EXECUTE PROCEDURE moddatetime(updated_at)
        """)

    op.create_index(
        "ix_meal_log_cursor", "meal_log", ["user_id", "updated_at", "meal_id"]
    )

    # ------------------------------------------------------------------
    # daily_summary — updated_at
    # ------------------------------------------------------------------
    op.add_column(
        "daily_summary",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.execute("""
        CREATE TRIGGER daily_summary_set_updated_at
        BEFORE UPDATE ON daily_summary
        FOR EACH ROW
        EXECUTE PROCEDURE moddatetime(updated_at)
        """)
    op.create_index(
        "ix_daily_summary_cursor", "daily_summary", ["user_id", "updated_at", "id"]
    )

    # ------------------------------------------------------------------
    # weekly_summary — updated_at
    # ------------------------------------------------------------------
    op.add_column(
        "weekly_summary",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.execute("""
        CREATE TRIGGER weekly_summary_set_updated_at
        BEFORE UPDATE ON weekly_summary
        FOR EACH ROW
        EXECUTE PROCEDURE moddatetime(updated_at)
        """)
    op.create_index(
        "ix_weekly_summary_cursor", "weekly_summary", ["user_id", "updated_at", "id"]
    )

    # ------------------------------------------------------------------
    # integration_token
    # ------------------------------------------------------------------
    op.create_table(
        "integration_token",
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
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "scopes",
            ARRAY(sa.String()),
            nullable=False,
            server_default="{nutrition:read}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_integration_token_token_hash", "integration_token", ["token_hash"]
    )
    op.execute("ALTER TABLE integration_token ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_integration_token_token_hash", table_name="integration_token")
    op.drop_table("integration_token")

    op.drop_index("ix_weekly_summary_cursor", table_name="weekly_summary")
    op.execute("DROP TRIGGER IF EXISTS weekly_summary_set_updated_at ON weekly_summary")
    op.drop_column("weekly_summary", "updated_at")

    op.drop_index("ix_daily_summary_cursor", table_name="daily_summary")
    op.execute("DROP TRIGGER IF EXISTS daily_summary_set_updated_at ON daily_summary")
    op.drop_column("daily_summary", "updated_at")

    op.drop_index("ix_meal_log_cursor", table_name="meal_log")
    op.execute("DROP TRIGGER IF EXISTS meal_log_set_updated_at ON meal_log")
    op.drop_column("meal_log", "deleted_at")
    op.drop_column("meal_log", "updated_at")

    op.execute("DROP EXTENSION IF EXISTS moddatetime")
