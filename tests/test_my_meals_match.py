"""Phrase-match tests for find_saved_meal (My Meals before USDA).

Covers the pure selection logic (`_best_saved_match` / `_contiguous_sublist`)
directly with lightweight stand-in meals; DB loading + per-user isolation are
exercised in test_my_meals_api.py.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.agent.tools.saved_meals import _best_saved_match, _contiguous_sublist


def _meal(name_normalized: str) -> SimpleNamespace:
    return SimpleNamespace(name_normalized=name_normalized)


def test_contiguous_sublist() -> None:
    assert _contiguous_sublist(["chicken", "biryani"], ["chicken", "biryani"])
    assert _contiguous_sublist(
        ["i", "had", "chicken", "biryani"], ["chicken", "biryani"]
    )
    # Non-contiguous tokens do not match.
    assert not _contiguous_sublist(
        ["chicken", "curry", "biryani"], ["chicken", "biryani"]
    )
    # Needle longer than haystack, or empty needle.
    assert not _contiguous_sublist(["rice"], ["fried", "rice"])
    assert not _contiguous_sublist(["rice"], [])


def test_bare_name_still_matches() -> None:
    meals = [_meal("chicken biryani")]
    assert _best_saved_match("chicken biryani", meals) is meals[0]


def test_name_inside_sentence_matches() -> None:
    meals = [_meal("chicken biryani")]
    assert _best_saved_match("I had chicken biryani for lunch", meals) is meals[0]


def test_co_mentioned_food_still_hits_saved_dish() -> None:
    # No leftover guard: the saved dish wins even with other food in the message.
    meals = [_meal("chicken biryani")]
    assert _best_saved_match("chicken biryani and a coke", meals) is meals[0]


def test_longest_match_wins() -> None:
    fried_rice = _meal("fried rice")
    rice = _meal("rice")
    # Order is most-recent-first; the more specific name must win regardless.
    assert _best_saved_match("fried rice", [rice, fried_rice]) is fried_rice
    assert _best_saved_match("fried rice", [fried_rice, rice]) is fried_rice


def test_tie_breaks_to_most_recent() -> None:
    newer = _meal("green smoothie")
    older = _meal("green smoothie")
    # meals arrive most-recent-first → first equal-length match wins.
    assert _best_saved_match("a green smoothie please", [newer, older]) is newer


def test_no_saved_name_present_returns_none() -> None:
    meals = [_meal("chicken biryani")]
    assert _best_saved_match("grilled salmon", meals) is None


def test_empty_and_filler_only_input_returns_none() -> None:
    meals = [_meal("chicken biryani")]
    assert _best_saved_match("", meals) is None
    assert _best_saved_match("...", meals) is None


def test_case_and_punctuation_insensitive() -> None:
    meals = [_meal("chicken biryani")]
    assert _best_saved_match("  Chicken  Biryani! ", meals) is meals[0]


def test_renamed_meal_recalled_by_new_name_not_old() -> None:
    # FR-007: matching reads name_normalized, so a rename moves the trigger.
    meal = _meal("chicken biryani")
    assert _best_saved_match("chicken biryani", [meal]) is meal

    meal.name_normalized = "biryani"
    assert _best_saved_match("had biryani for lunch", [meal]) is meal
    # A superset phrase still contains the new name, so it keeps matching.
    assert _best_saved_match("chicken biryani", [meal]) is meal

    meal.name_normalized = "dinner bowl"
    assert _best_saved_match("chicken biryani", [meal]) is None
    assert _best_saved_match("my dinner bowl", [meal]) is meal
