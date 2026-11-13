"""Patient-facing text for a checked recipe (FR-032).

The model writes only the recipe's name, intro and steps. The sentence naming
the constraints is built here from the check's ``applied`` list, so it cannot
claim a constraint that was not checked.
"""

from __future__ import annotations

from backend.safety.checker import Applied, CheckResult
from backend.safety.recipe import Recipe


def _join(items: list[str]) -> str:
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def constraint_sentence(applied: list[Applied]) -> str:
    """One plain sentence naming what the recipe was kept to and why.

    Args:
        applied: The confirmed entries the check evaluated.

    Returns:
        E.g. "Kept this free of peanut and low in sodium because of your
        peanut allergy and your sodium limit of 600 mg per meal."; "" when
        nothing applied.
    """
    if not applied:
        return ""
    kept = _join(_unique([a.kept for a in applied]))
    because = _join(_unique([a.phrase for a in applied]))
    return f"Kept this {kept} because of {because}."


def _missing_note(missing: str) -> str:
    nutrient, _, condition = missing.partition(" limit for ")
    if not condition:
        return f"No value is set for {missing}; ask your dietitian."
    return f"No {nutrient} limit is set for your {condition}; ask your dietitian."


def render_recipe(recipe: Recipe, result: CheckResult) -> str:
    """The recipe as shown to the patient.

    Args:
        recipe: A recipe that passed the check.
        result: Its check result.

    Returns:
        Name, intro, ingredients in grams, numbered steps, time, the
        constraint sentence, then missing-value, conflict and other notes.
    """
    servings = f" (serves {recipe.servings})" if recipe.servings > 1 else ""
    lines = [recipe.name, "", recipe.intro, "", f"Ingredients{servings}:"]
    lines += [f"- {i.qty_g:g} g {i.name}" for i in recipe.ingredients]
    lines += ["", "Steps:"]
    lines += [f"{n}. {step}" for n, step in enumerate(recipe.steps, start=1)]
    lines += [
        "",
        f"Time: {recipe.active_minutes} min hands-on, "
        f"{recipe.total_minutes} min total.",
    ]
    extras = [
        constraint_sentence(result.applied),
        *(_missing_note(m) for m in result.missing_values),
        *(c.note for c in result.conflicts),
        *result.notes,
    ]
    lines += ["", *[line for line in extras if line]]
    return "\n".join(lines).rstrip()
