"""Tests for the nutrient catalogue (spec 008 FR-001, FR-004a, FR-006, FR-015)."""

from __future__ import annotations

import copy

import pytest
import yaml
from pydantic import ValidationError

from backend.config import _CATALOG_PATH as CATALOG_PATH
from backend.config import USDA_ONLY_KEYS, NutrientCatalog, get_catalog
from backend.nutrients import catalog


def _raw() -> dict:
    with CATALOG_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _entry(raw: dict, key: str) -> dict:
    return next(n for n in raw["nutrients"] if n["key"] == key)


def test_catalog_has_48_nutrients_in_5_groups() -> None:
    cat = get_catalog()
    assert len(cat.nutrients) == 48
    assert [g.id for g in cat.groups] == [
        "carbs",
        "fat",
        "other",
        "vitamins",
        "minerals",
    ]


def test_usda_only_is_exactly_the_eight_trace_elements() -> None:
    assert catalog.usda_only_keys() == USDA_ONLY_KEYS
    assert len(USDA_ONLY_KEYS) == 8


def test_both_sugar_spellings_map_to_total_sugars() -> None:
    assert catalog.key_for_usda_name("Total Sugars") == "total_sugars"
    assert catalog.key_for_usda_name("Sugars, Total") == "total_sugars"


def test_folate_prefers_dfe() -> None:
    assert catalog.usda_names_by_priority("folate")[0] == "Folate, DFE"


def test_stored_keys_exclude_column_and_derived() -> None:
    stored = catalog.stored_keys()
    assert "fiber" not in stored  # lives in meal_log.fiber_g
    assert "salt" not in stored  # derived from sodium
    assert len(stored) == 46


def test_estimable_keys_count() -> None:
    # 48 − fiber − salt − 8 USDA-only
    assert len(catalog.estimable_keys()) == 38
    assert not set(catalog.estimable_keys()) & USDA_ONLY_KEYS


def test_resolve_key_accepts_key_or_alias() -> None:
    assert catalog.resolve_key("vitamin_b12") == "vitamin_b12"
    assert catalog.resolve_key("Vitamin B-12") == "vitamin_b12"
    assert catalog.resolve_key("Iron, Fe") == "iron"
    assert catalog.resolve_key("unobtainium") is None


def test_public_view_hides_server_fields() -> None:
    view = catalog.public_view()
    assert len(view["nutrients"]) == 48
    for n in view["nutrients"]:
        assert not {"usda_names", "max_per_100g", "column"} & n.keys()
    salt = next(n for n in view["nutrients"] if n["key"] == "salt")
    assert salt["derived"] == {"from": "sodium", "factor": 0.0025}


def test_upper_limits_moved_into_catalogue() -> None:
    assert catalog.nutrient("sodium").upper_limit.value == 2300
    assert sum(1 for n in get_catalog().nutrients if n.upper_limit) == 8


def test_rejects_duplicate_keys() -> None:
    raw = _raw()
    raw["nutrients"].append(copy.deepcopy(_entry(raw, "iron")))
    with pytest.raises(ValidationError, match="duplicate"):
        NutrientCatalog.model_validate(raw)


def test_rejects_column_and_derived_together() -> None:
    raw = _raw()
    _entry(raw, "salt")["column"] = "salt_g"
    with pytest.raises(ValidationError, match="at most one"):
        NutrientCatalog.model_validate(raw)


def test_rejects_derived_with_usda_names() -> None:
    raw = _raw()
    _entry(raw, "salt")["usda_names"] = ["Salt"]
    with pytest.raises(ValidationError, match="derived"):
        NutrientCatalog.model_validate(raw)


def test_rejects_wrong_usda_only_set() -> None:
    raw = _raw()
    _entry(raw, "iron")["usda_only"] = True
    with pytest.raises(ValidationError, match="usda_only"):
        NutrientCatalog.model_validate(raw)


@pytest.mark.parametrize(
    ("field", "value"),
    [("unit", "kg"), ("group", "snacks"), ("direction", "up"), ("status", "gone")],
)
def test_rejects_bad_enums(field: str, value: str) -> None:
    raw = _raw()
    _entry(raw, "iron")[field] = value
    with pytest.raises(ValidationError):
        NutrientCatalog.model_validate(raw)
