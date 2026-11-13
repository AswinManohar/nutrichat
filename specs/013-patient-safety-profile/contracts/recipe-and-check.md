# Contract: Recipe, CheckResult and the suggestion loop

Internal contract between `agent/suggest.py` (model side) and
`backend/safety/` (deterministic side). All models are Pydantic with
`extra="forbid"`.

## Recipe (model output, FR-008)

```python
class Ingredient(BaseModel):
    name: str            # plain food name, USDA-searchable ("peanut oil", "brown rice, cooked")
    qty_g: float         # > 0; grams as eaten (ml for drinks counts as g)

class Recipe(BaseModel):
    name: str
    intro: str           # ≤ 200 chars, shown above the recipe
    ingredients: list[Ingredient]        # 1-20
    texture: Literal["liquid", "puree", "minced_moist", "soft_bite_sized", "regular"]
    crunchy_or_dry: bool
    steps: list[str]                     # 1-12, each ≤ 200 chars
    active_minutes: int                  # hands-on time, ≥ 0
    total_minutes: int                   # ≥ active_minutes
    equipment: list[str]                 # may be empty
    servings: int = 1                    # totals are per serving
```

A response that fails validation, or has an ingredient with `qty_g <= 0`, is
**malformed**: it counts as a failed attempt with rule `malformed`.

## Resolved totals (safety/recipe.py)

```python
class ResolvedIngredient(BaseModel):
    name: str
    qty_g: float
    fdc_id: int | None          # None = not resolved
    usda_description: str | None
    match_confidence: float

class NutrientTotal(BaseModel):
    nutrient: str               # sodium | potassium | phosphorus | protein | fluid | carbohydrate | vitamin_k | kcal
    amount: float | None        # None = unknown (some contribution unresolved or missing)
    unit: str
    unknown_from: list[str]     # ingredient names that made it unknown
    approximate: bool           # true for fluid (water content), R7
```

Totals are per serving, from `usda_local` only (R7).

## CheckResult (safety/checker.py, FR-009)

```python
class Failure(BaseModel):
    rule: Literal["malformed", "allergen", "food_exclusion", "diet_setting",
                  "interaction", "nutrient_limit", "texture", "physical"]
    entry_id: str | None
    detail: str                 # "allergen: peanut (ingredient: peanut oil)"
    value: float | None = None
    limit: float | None = None
    unit: str | None = None

class Applied(BaseModel):
    entry_id: str
    phrase: str                 # "your peanut allergy", "your sodium limit of 600 mg per meal"

class CheckResult(BaseModel):
    passed: bool
    failures: list[Failure]
    applied: list[Applied]      # every confirmed entry that was evaluated
    missing_values: list[str]   # "potassium limit for chronic kidney disease" (FR-033)
    conflicts: list[str]        # stricter-rule notes (FR-035)
    profile_version: str
    entry_ids: list[str]
    table_versions: dict[str, str]
    totals: list[NutrientTotal]
    attempt: int
```

`check()` is a pure function of `(Recipe, resolved ingredients, confirmed
entries, today's intake, tables)`. It never raises on a bad recipe; it returns
failures. It raises `FoodDbUnavailable` when the SQLite file cannot be read, and
the caller shows the retry message (spec edge case "Food database down").

## Suggestion loop (agent/suggest.py, FR-011)

```text
profile = load hard profile            # failure → "try again" reply, no meal (FR-007)
for attempt in 1..3:
    recipe = generate(request, profile block, soft block, history, prior failures)
    result = check(recipe)
    if result.passed: record recommendation; render; return
    record check_failure(outcome="regenerated" or "dropped")
reply "no suitable meal this time" (FR-011, US2-6)
```

Rendered reply = `intro` + ingredient list + steps + one constraint sentence
built from `applied` ("Kept this soft and low in sodium because of your chewing
difficulty and your sodium limit.") + missing-value and conflict notes. The
model never writes the constraint sentence.

## Reply guardrail (agent/coaching.py + safety/reply_guard.py, R10)

```python
@_response_agent.output_validator
async def guard_reply(ctx: RunContext[_ResponseDeps], text: str) -> str:
    verdict = await reply_guard.check(text, ctx.deps.confirmed_entries, tables)
    if verdict.violations:
        raise ModelRetry(verdict.retry_reason)   # e.g. "the reply suggests peanut butter; the user has a peanut allergy"
    return text
```

```python
class GuardVerdict(BaseModel):
    violations: list[Failure]        # rule = allergen | food_exclusion | diet_setting | interaction
    layer: Literal["lexical", "usda", "glide", "none"]
    glide_probability: float | None
    retry_reason: str
```

- Layers run in order and stop at the first violation: lexical terms, food
  phrases resolved through `usda_local`, then the GLiDE judgment
  (`agent/reply_judge.py`) when a food phrase was found without a violation.
  A GLiDE probability ≥ `safety.reply_guard_min_probability` is a violation.
- GLiDE unavailable: the result of layers 1-2 stands, and the span records
  `layer_skipped=glide`.
- `retries=2` on the agent. After the last retry fails, the reply is replaced
  with `safety.reply_guard_fallback_text` and a `check_failure` with outcome
  `reply_replaced` is stored.
