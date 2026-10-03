"""Compute plausibility caps (max_per_100g) for tracked nutrients (spec 008 R8).

For each stored, estimable key with at least 30% USDA coverage in the bundled
catalogue, the cap is 1.5 × the largest per-100 g value USDA reports (a
percentile cut wrongly rejected real extremes such as cod liver oil's
vitamin D). Sparse or USDA-less keys use a hand-set cap from food-composition
maxima, raised to 1.5 × the largest USDA value when USDA has any. Gram caps
never exceed 100 g per 100 g. USDA-only keys are never estimated, so they get
no cap.

Usage:
    PYTHONPATH=src python -m backend.scripts.compute_micro_caps [--write]

Without ``--write`` the caps are only printed for review.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import zlib
from pathlib import Path

from backend.agent.tools import usda_local
from backend.config import _CATALOG_PATH
from backend.nutrients import catalog
from backend.nutrients.resolve import per_100g_from_usda

_MIN_COVERAGE = 0.30
_HEADROOM = 1.5

# Per 100 g, in the catalogue unit. Upper ends of published food composition
# (e.g. pure sugar, table salt, kelp, brewer's yeast, dry tea leaves).
_HAND_CAPS: dict[str, float] = {
    "added_sugars": 100.0,  # g — pure sugar
    "chloride": 60_000.0,  # mg — table salt is ~60% chloride
    "chromium": 1_000.0,  # mcg
    "iodine": 300_000.0,  # mcg — dried kelp
    "molybdenum": 1_000.0,  # mcg
    "biotin": 1_000.0,  # mcg
    "fluoride": 400_000.0,  # mcg — dry tea leaves
}


def _values_by_key(db_path: Path) -> tuple[dict[str, list[float]], int]:
    """Per-100 g USDA values for every stored key, plus the food count."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    values: dict[str, list[float]] = {k: [] for k in catalog.stored_keys()}
    n_foods = 0
    for (blob,) in conn.execute("SELECT nutrients_z FROM food"):
        n_foods += 1
        mapped = per_100g_from_usda(json.loads(zlib.decompress(blob)), estimates={})
        for key, (value, _) in mapped.items():
            values[key].append(value)
    conn.close()
    return values, n_foods


def compute_caps(db_path: Path) -> dict[str, float]:
    """Return key -> cap for every estimable key."""
    values, n_foods = _values_by_key(db_path)
    caps: dict[str, float] = {}
    for key in catalog.estimable_keys():
        vals = sorted(values[key])
        if len(vals) / n_foods >= _MIN_COVERAGE:
            caps[key] = vals[-1] * _HEADROOM
        else:
            observed = vals[-1] * _HEADROOM if vals else 0.0
            caps[key] = max(_HAND_CAPS.get(key, 0.0), observed)
        if catalog.nutrient(key).unit == "g":
            caps[key] = min(caps[key], 100.0)
        if caps[key] <= 0:
            raise ValueError(f"no cap derivable for {key}; add a hand cap")
        caps[key] = float(f"{caps[key]:.4g}")
    return caps


def write_caps(caps: dict[str, float], yaml_path: Path) -> None:
    """Rewrite ``max_per_100g`` lines in nutrients.yaml in place."""
    text = yaml_path.read_text(encoding="utf-8")
    for key, cap in caps.items():
        pattern = re.compile(
            rf"(  - key: {re.escape(key)}\n(?:    .*\n)*?    max_per_100g: )\S+"
        )
        text, count = pattern.subn(rf"\g<1>{cap:g}", text, count=1)
        if count != 1:
            raise ValueError(f"could not find max_per_100g for {key}")
    yaml_path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="update nutrients.yaml")
    args = parser.parse_args()
    caps = compute_caps(usda_local.database_path())
    for key, cap in caps.items():
        print(f"{key:22} {cap:g} {catalog.nutrient(key).unit}")
    if args.write:
        write_caps(caps, _CATALOG_PATH)
        print(f"wrote {len(caps)} caps to {_CATALOG_PATH}")


if __name__ == "__main__":
    main()
