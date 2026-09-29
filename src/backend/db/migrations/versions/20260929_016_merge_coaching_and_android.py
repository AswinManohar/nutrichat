"""Merge the coaching-feedback (014) and Android (015) migration branches.

Revision ID: 016_merge
Revises: 014, 015_food_correction
Create Date: 2026-09-29

No schema changes: 014 (coaching_response, guideline_chunk) and 015
(food_correction) touch disjoint tables, so this only joins the two heads.
"""

from __future__ import annotations

revision = "016_merge"
down_revision = ("014", "015_food_correction")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
