#!/usr/bin/env python3
"""Compute WCAG contrast for text/background token pairs in MealsyColors.kt.

Usage: uv run --with rich python contrast_check.py <path-to-MealsyColors.kt>
(No third-party deps actually required; plain python3 is fine.)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TOKEN_RE = re.compile(r"(\w+)\s*=\s*Color\(0x(FF|[0-9A-Fa-f]{2})([0-9A-Fa-f]{6})\)")


def parse_block(text: str) -> dict[str, tuple[int, int, int]]:
    colors = {}
    for m in TOKEN_RE.finditer(text):
        name, _alpha, rgb = m.groups()
        r = int(rgb[0:2], 16)
        g = int(rgb[2:4], 16)
        b = int(rgb[4:6], 16)
        colors[name] = (r, g, b)
    return colors


def srgb_to_linear(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return (
        0.2126 * srgb_to_linear(r)
        + 0.7152 * srgb_to_linear(g)
        + 0.0722 * srgb_to_linear(b)
    )


def contrast_ratio(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    l1 = relative_luminance(c1) + 0.05
    l2 = relative_luminance(c2) + 0.05
    return max(l1, l2) / min(l1, l2)


# (text_token, bg_token, is_large_text)
PAIRS = [
    ("ink", "canvas", False),
    ("ink", "surface", False),
    ("muted", "canvas", False),
    ("muted", "surface", False),
    ("inactive", "canvas", False),
    ("inactive", "surface", False),
    ("oliveText", "olive", False),
    ("oliveTrackLabel", "oliveTrack", False),
    ("oliveTrackValue", "oliveTrack", False),
    ("userBubbleText", "userBubble", False),
    ("butterText", "butter", False),
    ("pinkText", "pink", False),
    ("leafText", "leaf", False),
    ("powderText", "powder", False),
    ("terracottaText", "terracotta", False),
    ("terracottaOutlineText", "canvas", False),
    ("terracottaOutlineText", "surface", False),
    ("navActive", "navBar", False),
    ("navInactive", "navBar", False),
    ("fabIcon", "fab", False),
]


def main() -> None:
    default_path = (
        Path(__file__).resolve().parent.parent
        / "core/ui/src/main/java/app/mealsy/android/design/theme/MealsyColors.kt"
    )
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_path
    src = path.read_text()

    light_start = src.index("fun lightMealsyColors")
    dark_start = src.index("fun darkMealsyColors")
    light_block = src[light_start:dark_start]
    dark_block = src[dark_start:]

    for theme_name, block in (("LIGHT", light_block), ("DARK", dark_block)):
        colors = parse_block(block)
        print(f"\n=== {theme_name} ===")
        for text_tok, bg_tok, large in PAIRS:
            if text_tok not in colors or bg_tok not in colors:
                continue
            ratio = contrast_ratio(colors[text_tok], colors[bg_tok])
            threshold = 3.0 if large else 4.5
            status = "PASS" if ratio >= threshold else "FAIL"
            print(
                f"{status:4} {text_tok:22} on {bg_tok:16} "
                f"ratio={ratio:.2f} (need {threshold})"
            )


if __name__ == "__main__":
    main()
