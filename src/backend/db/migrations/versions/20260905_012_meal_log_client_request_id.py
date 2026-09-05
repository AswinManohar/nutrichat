"""meal_log.client_request_id for idempotent mobile replays.

The Android client may retry POST /meals/log-items after a dropped response
(flaky mobile network) without knowing whether the first attempt landed.
Recording the client-generated request id and enforcing uniqueness per user
lets the handler detect a replay and return the original meal instead of
double-logging.

Revision ID: 012
Revises: 011
Create Date: 2026-09-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meal_log",
        sa.Column("client_request_id", sa.String(64), nullable=True),
    )
    op.create_index(
        "uq_meal_log_user_client_request",
        "meal_log",
        ["user_id", "client_request_id"],
        unique=True,
        postgresql_where=sa.text("client_request_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_meal_log_user_client_request", table_name="meal_log")
    op.drop_column("meal_log", "client_request_id")
