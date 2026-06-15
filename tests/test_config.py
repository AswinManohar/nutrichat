from __future__ import annotations

from backend.config import get_tunables


def test_nutrient_checkup_rda_loaded() -> None:
    rda = get_tunables().nutrient_checkup.rda
    assert rda["Protein"] == 50
    assert rda["Fiber"] == 28
    assert rda["Sugar"] == 50
    assert rda["Vitamin C"] == 90
    assert rda["Vitamin D"] == 20
    assert rda["Iron"] == 18
    assert rda["Calcium"] == 1300
    assert rda["Vitamin B-12"] == 2.4
