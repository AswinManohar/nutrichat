"""Test factories for spec 008 micronutrient shapes (shared by later tests)."""

from __future__ import annotations

from backend.agent.tools.usda import USDAResult
from backend.nutrients.models import MicroValue

MicroSpec = dict[str, tuple[float | None, str]]


def make_micros(spec: MicroSpec) -> dict[str, MicroValue]:
    """Build ``{key: MicroValue}`` from ``{key: (amount, source)}``."""
    return {k: MicroValue(amount=a, source=s) for k, (a, s) in spec.items()}


def make_usda_result(
    food_name: str = "banana, raw",
    qty_g: float = 100.0,
    fdc_id: int = 1105314,
    micros: MicroSpec | None = None,
    **macros: float,
) -> USDAResult:
    """Build a USDAResult with sensible macro defaults and the given micros."""
    base = {
        "kcal": 89.0,
        "protein_g": 1.1,
        "carbs_g": 22.8,
        "fat_g": 0.3,
        "fiber_g": 2.6,
        "sugar_g": 12.2,
        "sat_fat_g": 0.1,
    }
    base.update(macros)
    return USDAResult(
        fdc_id=fdc_id,
        food_name=food_name,
        qty_g=qty_g,
        match_confidence=0.9,
        candidates=[],
        nutrients={},
        micros=make_micros(micros or {}),
        source="USDA" if fdc_id > 0 else "LLM_ESTIMATE",
        estimated=fdc_id <= 0,
        **base,
    )


def make_meal_micros(spec: dict[str, tuple[float, float, int]]) -> dict[str, dict]:
    """Build a ``meal_log.micros`` value from ``{key: (total, est, known)}``."""
    return {k: {"total": t, "est": e, "known": n} for k, (t, e, n) in spec.items()}
