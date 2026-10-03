from __future__ import annotations

from backend.config import get_tunables


def test_nutrient_checkup_keys_and_overrides_loaded() -> None:
    """Check-up picks catalogue keys; only view targets are overridden."""
    cfg = get_tunables().nutrient_checkup
    assert cfg.keys == [
        "protein",
        "fiber",
        "total_sugars",
        "vitamin_c",
        "vitamin_d",
        "iron",
        "calcium",
        "vitamin_b12",
    ]
    assert cfg.daily_value_overrides == {"protein": 50, "total_sugars": 50}
