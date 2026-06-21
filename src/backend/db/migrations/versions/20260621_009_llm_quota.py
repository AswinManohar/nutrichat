"""user_goal — llm_requests_used and llm_quota columns for per-user LLM quota.

Free tier default 50, paid tier set to 150 by billing on upgrade.
Existing rows receive 0 / 50 via server defaults — no backfill required.

Revision ID: 009
Revises: 008
Create Date: 2026-06-21
"""

from __future__ import annotations

from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE user_goal "
        "ADD COLUMN IF NOT EXISTS llm_requests_used INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE user_goal "
        "ADD COLUMN IF NOT EXISTS llm_quota INTEGER NOT NULL DEFAULT 50"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_goal DROP COLUMN IF EXISTS llm_quota")
    op.execute("ALTER TABLE user_goal DROP COLUMN IF EXISTS llm_requests_used")
