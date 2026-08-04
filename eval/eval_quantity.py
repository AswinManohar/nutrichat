"""Quantity eval: does the confirmation card reflect the stated count?

For each food we run the singular phrase ("one egg") and a counted phrase
("two eggs") through the exact pipeline that fills the confirmation card —
extract_entities -> usda_lookup_batch — and check that the card's grams and
calories scale by the stated count. Ratio-based so it doesn't depend on the
model's choice of per-unit grams; it only has to be internally linear.

Run: uv run --env-file .env python eval/eval_quantity.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from src.backend.agent.tools.meals import extract_entities
from src.backend.agent.tools.usda import usda_lookup_batch

# (label, singular phrase, counted phrase, expected count)
CASES = [
    ("egg", "one egg", "two eggs", 2),
    ("banana", "a banana", "three bananas", 3),
    ("bacon slice", "one slice of bacon", "four slices of bacon", 4),
    ("wheat bread slice", "one slice of whole wheat bread", "two slices of whole wheat bread", 2),
    ("chicken wing", "one chicken wing", "six chicken wings", 6),
]

TOL = 0.25  # counted value must land within ±25% of count × singular


def _first_item(phrase: str):
    """Extract the first food entity's card row (qty_g + macros)."""
    ents = [e for e in extract_entities(phrase).entities if e.qty_g > 0]
    return ents[0] if ents else None


async def _card_row(phrase: str) -> dict | None:
    ent = _first_item(phrase)
    if ent is None:
        return None
    result = (await usda_lookup_batch([ent]))[0]
    return {
        "matched": result.food_name,
        "qty_g": round(result.qty_g, 1),
        "kcal": round(result.kcal, 1),
        "protein_g": round(result.protein_g, 1),
    }


async def main() -> None:
    print(f"{'food':<20} {'count':>5} {'1x g':>7} {'Nx g':>7} {'g ratio':>8} "
          f"{'1x kcal':>8} {'Nx kcal':>8} {'kcal ratio':>10}  verdict")
    print("-" * 100)
    passed = 0
    for label, singular, counted, n in CASES:
        one, many = await asyncio.gather(_card_row(singular), _card_row(counted))
        if not one or not many or one["qty_g"] <= 0:
            print(f"{label:<20} {n:>5}  EXTRACTION FAILED")
            continue
        g_ratio = many["qty_g"] / one["qty_g"]
        k_ratio = many["kcal"] / one["kcal"] if one["kcal"] else 0.0
        ok = abs(g_ratio - n) <= n * TOL
        passed += ok
        print(f"{label:<20} {n:>5} {one['qty_g']:>7} {many['qty_g']:>7} "
              f"{g_ratio:>7.2f}x {one['kcal']:>8} {many['kcal']:>8} "
              f"{k_ratio:>9.2f}x  {'PASS' if ok else 'FAIL'}")

    print("-" * 100)
    print(f"{passed}/{len(CASES)} cases: counted grams within ±{int(TOL*100)}% of "
          f"count × singular")
    # Headline the eggs case explicitly (the reported example).
    egg_one, egg_two = await asyncio.gather(_card_row("one egg"), _card_row("two eggs"))
    print(f"\n'two eggs' card row -> {egg_two['matched'][:40]!r}: "
          f"{egg_two['qty_g']}g, {egg_two['kcal']} kcal, {egg_two['protein_g']}g protein "
          f"(vs one egg: {egg_one['qty_g']}g, {egg_one['kcal']} kcal)")


if __name__ == "__main__":
    asyncio.run(main())
