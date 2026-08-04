"""MealLog gains a nullable `label` column for dish-name history retrieval."""

from __future__ import annotations

from backend.db.models import MealLog


def test_meal_log_has_label_column() -> None:
    col = MealLog.__table__.columns.get("label")
    assert col is not None, "meal_log.label column missing"
    assert col.nullable is True


def test_meal_log_label_index_present() -> None:
    index_names = {ix.name for ix in MealLog.__table__.indexes}
    assert "ix_meal_log_user_label" in index_names
