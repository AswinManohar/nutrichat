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

from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent (Postgres IF NOT EXISTS) so it is safe to run against a DB
    # where the additive column/index were already applied out-of-band.
    op.execute("ALTER TABLE meal_log ADD COLUMN IF NOT EXISTS label text")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_meal_log_user_label "
        "ON meal_log (user_id, label)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_meal_log_user_label")
    op.execute("ALTER TABLE meal_log DROP COLUMN IF EXISTS label")
