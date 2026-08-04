# Saved-Meal Phrase Match (My Meals before USDA) — Design Spec

**Date:** 2026-06-19
**Status:** Approved
**Scope:** Make the meal-logging graph match a saved **My Meal** when its name
appears *inside* a typed sentence (e.g. "I had chicken biryani for lunch"), not
only when the whole message is exactly the saved name. The saved breakdown is
then used instead of fresh USDA resolution.

Builds on `2026-06-17-my-meals-design.md` (saved meals + the `saved_lookup`
graph node) and `2026-06-19-my-meals-customize-design.md`.

---

## 1. Problem

The graph already checks My Meals before USDA — `saved_lookup_node`
(`graph.py:75`) runs `find_saved_meal` before extraction, and on a hit routes
straight to the confirmation card, skipping extract→USDA (`graph.py:338`).

But `find_saved_meal` (`saved_meals.py:19`) is **whole-message normalized-exact
match**: it normalizes the *entire* input and compares it to `name_normalized`.
So only a bare "chicken biryani" hits. "I had chicken biryani for lunch",
"biryani and a coke", etc. all miss and fall through to USDA — even though the
user clearly named a saved dish.

## 2. Decisions (locked with user)

- **Match a saved name as a contiguous phrase inside the message.** Surrounding
  words ("I had … for lunch") are ignored by the phrase match.
- **Longest match wins** when several saved names match — most specific dish.
- **No leftover guard.** If the message also names other food
  ("chicken biryani and a coke"), the saved dish still wins and loads; the other
  food is not separately resolved. (User choice; the card still requires confirm,
  so the result is visible, not auto-logged.)
- **Deterministic, no LLM.** Phrase matching over the user's small saved-meal set
  runs on every message; no extra model call. Fuzzy/typo/variant matching is
  deferred to the `user_meal.embedding` V2.
- **No graph topology change.** Only `find_saved_meal`'s matching logic changes;
  it still returns `UserMeal | None`, so `saved_lookup_node` and the API
  re-export are untouched.

## 3. Algorithm

`find_saved_meal(user_id, text) -> UserMeal | None`:

1. Normalize `text` with the existing `normalize_meal_name` (lowercase, strip
   punctuation, collapse whitespace) → split into a token list `msg_tokens`.
   Empty → return `None`.
2. Load the user's active saved meals (`deleted_at IS NULL`). Personal scale
   (handful–dozens); load all and match in Python.
3. For each saved meal, tokenize its stored `name_normalized` → `name_tokens`.
   It is a candidate if `name_tokens` appears as a **contiguous sublist** of
   `msg_tokens`.
4. Among candidates, return the one with the most `name_tokens` (longest /
   most specific). Ties broken by most recent `created_at`.
5. No candidate → `None` (falls through to extract→USDA, unchanged).

`name_normalized` is already stored at save time, so no per-row re-normalization
of names is needed beyond a whitespace split.

## 4. Components

- `src/backend/agent/tools/saved_meals.py`
  - Rewrite `find_saved_meal` matching from whole-string equality to contiguous
    token-sublist containment with longest-match selection.
  - Add a small private `_contiguous_sublist(haystack, needle) -> bool` helper.
  - Signature, return type, and `__all__` unchanged.
- No changes to `graph.py`, `orchestrator.py`, the API, or the frontend.

## 5. Data flow

"I had chicken biryani for lunch" → `saved_lookup_node` → `find_saved_meal`
tokenizes to `[i, had, chicken, biryani, for, lunch]`; saved
`chicken biryani` → `[chicken, biryani]` is a contiguous sublist → **hit** →
`saved_meal_to_results` loads the saved ingredients → card presented (skips
extract→USDA), exactly as the existing saved path.

## 6. Tradeoffs / known limitations

- **Single-common-word saved names.** A saved meal named "rice" matches inside
  "fried rice" when "fried rice" is not also saved, loading the saved rice and
  ignoring "fried". Longest-match mitigates this when the more specific dish is
  also saved. Accepted for V1; easy future dials if it bites: a minimum
  `name_tokens` length, or an opt-in "leftover food → fall through" guard.
- **Dropped co-mentioned foods.** Per §2, other foods in the same message are
  not resolved. The per-dish multi-item path (extract first, then per-entity
  saved lookup) is the future extension that removes this limitation.

## 7. Error handling

- Empty / punctuation-only input → `None` (unchanged).
- DB error loading saved meals → log + return `None` (degrade to the normal
  USDA path; never block logging on a My Meals lookup failure).

## 8. Testing

| Case | Expectation |
|---|---|
| Bare name "chicken biryani" | hit (regression — still works) |
| Name inside sentence "I had chicken biryani for lunch" | hit |
| Co-mentioned food "chicken biryani and a coke" | hit on biryani (no leftover guard) |
| Longest match: "fried rice" + "rice" both saved, input "fried rice" | hits "fried rice" |
| No saved name present "grilled salmon" | miss → `None` |
| Per-user isolation: other user's saved meal | miss |
| Case / whitespace / punctuation variants | hit |
| Empty / filler-only input | `None` |

## 9. Out of scope (V1)

Per-dish matching across genuine multi-item meals; fuzzy/typo/embedding match
(`user_meal.embedding` V2); any change to graph topology, confirmation, or
logging.

## 10. File map

| File | Change |
|---|---|
| `src/backend/agent/tools/saved_meals.py` | phrase-match `find_saved_meal` + `_contiguous_sublist` helper |
| `tests/test_my_meals_match.py` | phrase-in-sentence, longest-match, isolation, miss cases |
