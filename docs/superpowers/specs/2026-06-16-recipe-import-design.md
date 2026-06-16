# Recipe Import — Design Spec

**Status:** Approved (2026-06-16)
**Issue:** new (recipe-link / pasted-recipe import → macros & micros)

## Goal

Let a user log a recipe they followed by pasting its **URL or its ingredient
text**. The agent extracts the ingredient list and yield, resolves each
ingredient against USDA (macros **and** micros), and logs the portion the user
ate — scaled by **servings eaten ÷ total servings**.

## Decisions (locked with user)

- **Portion model:** scale by servings eaten (`servings_eaten / total_servings`).
- **Input:** a recipe **URL** or **pasted ingredient text**. No web search, no vision.
- **Architecture:** Approach A — a new `recipe.py` tool feeding a recipe branch
  in the existing LangGraph flow, reusing `usda_lookup_batch`, the confirmation
  card, and the log path.
- **JSON-LD parsing:** stdlib `html.parser` (no new dependency). `beautifulsoup4`
  only if real sites later prove it necessary.

## Architecture

### Routing
Extend the orchestrator intent classifier from `{log_meal, coaching}` to
`{log_meal, coaching, recipe}`. Deterministic fast-path: **any message
containing an http(s) URL → `recipe`** (skip the LLM). Pasted-text recipes are
classified by the LLM. This reuses existing routing rather than adding a
parallel entry point.

### Graph branch (maximizes reuse)
`AgentState` gains:
- `recipe_input: str | None` — the raw URL or pasted text.
- `recipe_meta: dict | None` — `{title, total_servings, source_url}`.

`router_node` conditional:
- `recipe_input` present → **`recipe_fetch`** node
- else image present → `classify`
- else → `extract`

`recipe_fetch` runs fetch → parse → `extract_entities()` on the ingredient
block, setting the normal `entities` list **plus** `recipe_meta`. It then flows
into the existing `usda_batch → present → log` path unchanged. The confirmation
card, per-ingredient gram editing, USDA macro/micro resolution, and logging are
all reused.

### The `recipe.py` tool
```
fetch_recipe(url_or_text: str) -> RecipeExtraction
```
`RecipeExtraction(BaseModel)`: `title: str | None`, `total_servings: float`
(default 1.0), `ingredient_lines: list[str]`, `source_url: str | None`.

Pipeline:
1. **URL input** → `aiohttp` GET with: connect/read timeout, response size cap
   (2 MB), `Content-Type: text/html` check, and an **SSRF guard** — scheme must
   be http/https; resolve the host and reject loopback, private, link-local, and
   reserved IPs; reject non-standard ports. On any violation, treat as
   unfetchable (graceful fallback, below).
   - Parse `<script type="application/ld+json">` blocks with stdlib
     `html.parser`; find a `schema.org/Recipe` object (handle `@graph` arrays);
     read `recipeIngredient[]` and `recipeYield` (parse leading integer; default 1).
2. **No JSON-LD Recipe found** → LLM-parse the page's visible text into
   `RecipeExtraction` via `make_llm` structured output.
3. **Pasted text input** (no URL) → straight to the LLM parser.

### Servings & scaling
The confirmation card gains an "I ate `[servings_eaten]` of `[total_servings]`
servings" control. `total_servings` is pre-filled from `recipeYield` (default 1);
both fields are editable. `servings_eaten` (default 1) and `total_servings` ride
the confirm action — same mechanism as `meal_type` — injected into graph state
on resume. `log_node` multiplies every macro and micro by
`servings_eaten / total_servings` before persisting. The user still picks the
meal category (breakfast/…/snack) as normal.

### Storage / provenance
`source_url`, `title`, `servings_eaten`, `total_servings` are stored in
`meal_log.flags` (JSONB). **No migration.** One `meal_log` row per recipe log.

## Error handling
- Fetch failure (timeout, 4xx/5xx, blocked by SSRF guard, oversize, non-HTML) →
  friendly reply: "Couldn't read that page — paste the ingredient list and I'll
  do the rest." (Routes the user into the pasted-text path.)
- No recipe found by JSON-LD **and** LLM → same graceful "paste the ingredients"
  reply.
- `total_servings` unknown → default 1.0; the card lets the user set it.
- Partial USDA matches → unchanged behavior; each estimated ingredient keeps its
  existing "≈ estimated (not in USDA)" flag on the card.

## Micronutrient caveat (explicit limitation)
Real micronutrients come only from confident USDA matches. The LLM-estimate
fallback (for unmatched ingredients) provides macros plus a few micros, not the
full panel. A recipe with several unmatched ingredients therefore yields
**partial** micros. This is surfaced honestly per-ingredient via the existing
estimated flag — no hidden inaccuracy.

## Testing
Unit tests, mocked fetch (no live network), mirroring the `usda`/`meals` test
style:
- JSON-LD parser extracts `recipeIngredient` + `recipeYield` from sample recipe
  HTML (including `@graph` form).
- LLM-fallback routing fires when no JSON-LD Recipe is present.
- SSRF guard rejects loopback/private/link-local IPs and non-http(s) schemes.
- Servings-scaling math (`servings_eaten / total_servings` applied to macros/micros).
- `total_servings` defaults to 1 when `recipeYield` is missing/unparseable.

## Out of scope
Web search by dish name; photo/vision recipe extraction; multi-recipe batches;
saving recipes to a personal cookbook. (Possible later features.)

## New dependencies
None.
