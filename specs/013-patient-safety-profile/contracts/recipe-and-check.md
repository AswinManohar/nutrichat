# Contract: Recipe, CheckResult and the suggestion loop

Internal contract between `agent/coaching/suggest.py` (model side) and
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
    inferred_zero_from: list[str]  # ingredients whose missing protein/carbohydrate was taken as 0
```

Totals are per serving, from `usda_local` only (R7).

Mass balance: for a resolved ingredient with no protein or carbohydrate value,
the missing macro is 0 when the proximates USDA does give (protein, fat,
carbohydrate, water, ash, alcohol; g per 100 g) sum to at least
`safety.mass_balance_min_g` (97). Otherwise it stays unknown and fails a limit.
Minerals and vitamin K are never inferred. `ResolvedIngredient.inferred_zero`
and `NutrientTotal.inferred_zero_from` record every inferred zero.

`safety/` may not import `backend.agent`, so the lookup is passed in:
`resolve(recipe, lookup)` takes `usda_local.lookup` and runs it in worker
threads, one per ingredient. `ResolvedIngredient` also carries `per_100g`
(each tracked nutrient per 100 g in the canonical unit, `None` = unknown or
unresolved); `totals_for(recipe, resolved)` derives the `NutrientTotal`s from
it, and `check()` puts them in the result. `qty_g` has no `> 0` constraint in
the model, so `malformed_reasons(recipe)` can flag it as a failed attempt; a
response that fails schema validation (`Recipe` limits above) is also a failed
attempt with rule `malformed` (the agent runs with `retries=0`).

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
    kept: str                   # what the recipe was kept to: "free of peanut", "low in sodium"

class Conflict(BaseModel):
    note: str                   # "Your sodium limits differ (800 mg and 400 mg a meal); ..."
    entry_ids: list[str]        # the entries involved; the first is the review item's subject

class CheckResult(BaseModel):
    passed: bool
    failures: list[Failure]
    applied: list[Applied]      # every confirmed entry that was evaluated
    missing_values: list[str]   # "potassium limit for chronic kidney disease" (FR-033)
    conflicts: list[Conflict]   # stricter-rule notes (FR-035)
    notes: list[str]            # e.g. logged items with no value, so today's total may be low
    profile_version: str
    entry_ids: list[str]
    table_versions: dict[str, str]
    totals: list[NutrientTotal]
    attempt: int
```

`check()` is a pure function of `(Recipe, resolved ingredients, entries,
today's intake, tables, attempt)`; `today_intake` maps a limit entry id to its
`LimitProgress` from `safety.limits.intake_today`. Pending entries are
ignored. It never raises on a bad recipe; it returns
failures. It raises `FoodDbUnavailable` when the SQLite file cannot be read, and
the caller shows the retry message (spec edge case "Food database down").

## Suggestion loop (agent/coaching/suggest.py, FR-011)

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

## Reply guardrail (agent/coaching/agent.py + safety/reply_guard.py, R10)

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

- `GuardVerdict` also carries `food_phrases` (phrases that resolved to a
  food), which decides whether layer 3 runs. Layers 1-2 are
  `reply_guard.scan(text, entries, tables, lookup)`; all three run in
  `agent/coaching/reply_judge.guard(text, entries, tables)`, which the validator calls.
  A guard that cannot run (tables or food database unreadable) replaces the
  reply with the fallback text.
- Layers run in order and stop at the first violation: lexical terms, food
  phrases resolved through `usda_local`, then the GLiDE judgment
  (`agent/coaching/reply_judge.py`) when a food phrase was found without a violation.
  A GLiDE probability ≥ `safety.reply_guard_min_probability` is a violation.
- Negation: a lexical hit is dropped when, in the same sentence, one of
  `safety.reply_guard_negations` precedes it within 3 words, or "-free" /
  " free" follows it. Dropped mentions are also removed before food phrases
  are looked up; if every hit was dropped and a food phrase remains, layer 3
  decides as before.
- GLiDE unavailable: the result of layers 1-2 stands, and the span records
  `layer_skipped=glide`.
- `retries=2` on the agent. After the last retry fails, the reply is replaced
  with `safety.reply_guard_fallback_text` and a `check_failure` with outcome
  `reply_replaced` is stored.
