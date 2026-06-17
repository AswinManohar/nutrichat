# Prompt Externalization — Design Spec

**Date:** 2026-06-16
**Status:** Draft (pending user review)
**Scope:** Move the large LLM prompts out of `tunables.yaml` into individual
Markdown files, leaving `tunables.yaml` for numeric/list constants only. No
behavior change — pure refactor with an unchanged public interface.

---

## 1. Problem

`src/backend/config/tunables.yaml` is 783 lines; ~400 of them are prompt prose
under the `prompts:` block, mixed with numeric tuning constants (models, USDA,
junk thresholds, routing signals, RDA, upper_limits). The largest prompts
(`coaching_response_system` ≈ 200 lines, `query_parse_system`) are unreadable
inside a YAML block scalar, painful to diff, and fight YAML escaping. Tuning a
number and editing a prompt are different activities living in one file.

## 2. Decisions (defaults — confirm on review)

- **Format:** Markdown (`.md`). Readable, diff-friendly, syntax-highlighted, no
  YAML escaping. (Alternative considered: `.txt` — rejected, no upside.)
- **Location:** `src/backend/config/prompts/`, beside `tunables.yaml`. (Alt: a
  top-level `prompts/` — rejected; keeps config self-contained.)
- **Interface unchanged:** callers keep using `get_tunables().prompts.<name>`;
  only the loader's source changes. Zero changes to `meals.py`,
  `orchestrator.py`, `coaching.py`, `context.py`, `workers/tasks.py`.

## 3. Design

### 3.1 File layout
One file per existing `PromptsConfig` field, named `<field>.md`:
```
src/backend/config/prompts/
  extraction_system.md
  image_classify_system.md
  correction_system.md
  intent_system.md
  query_parse_system.md
  coaching_response_system.md
  coaching_role_and_tone.md
  coaching_hard_constraints.md
  fact_extraction_system.md
  nutrition_estimate_system.md
```
File contents are the raw prompt text (the current YAML block-scalar body,
verbatim). Any leading comments currently above each YAML key move into the spec
or a short HTML comment at the top of each file — not into the prompt text.

### 3.2 Loader change (`src/backend/config/__init__.py`)
- Remove the `prompts:` block from `tunables.yaml`.
- Keep the `PromptsConfig` Pydantic model **unchanged** (same field names).
- After loading+validating `tunables.yaml` (now without `prompts`), construct
  `PromptsConfig` by reading each `<field>.md` from the prompts dir:
  ```python
  _PROMPTS_DIR = Path(__file__).parent / "prompts"

  def _load_prompts() -> PromptsConfig:
      fields = PromptsConfig.model_fields.keys()
      data = {}
      for name in fields:
          path = _PROMPTS_DIR / f"{name}.md"
          if not path.exists():
              raise FileNotFoundError(f"Missing prompt file: {path}")
          data[name] = path.read_text(encoding="utf-8").strip()
      return PromptsConfig(**data)
  ```
- `Tunables` no longer has `prompts` sourced from YAML. Two clean options
  (pick at implementation): (a) drop `prompts` from the `Tunables` model and
  expose prompts via a sibling `get_prompts()` accessor; **or (b, preferred)**
  keep `Tunables.prompts` but populate it in `get_tunables()` by merging the
  file-loaded `PromptsConfig` into the validated tunables object, so
  `get_tunables().prompts.<name>` keeps working unchanged. Preferred = (b) for
  zero caller churn.
- Validation: missing file, or a `.md` file with no matching model field, fails
  loudly at import (same "fail at boot, not mid-request" guarantee as today).
- `NUTRICHAT_TUNABLES_PATH` override still works for the YAML; prompts dir is
  resolved relative to the module (add `NUTRICHAT_PROMPTS_DIR` override for
  symmetry/tests).

### 3.3 What stays in `tunables.yaml`
Everything that is a tunable number or list: `models`, `token_limits`, `usda`,
`junk`, `memory`, `summaries`, `redis`, `day`, `nutrient_checkup`, `routing`,
`upper_limits`. The `prompts:` key is removed entirely.

## 4. Testing
- `test_config.py`: extend to assert (a) every `PromptsConfig` field loads
  non-empty from a file, (b) a missing prompt file raises at load, (c) a
  representative prompt's content matches a known substring (guards accidental
  truncation during the move).
- Run the full suite — no other test should change (interface is identical).
- Manual: `get_tunables().prompts.coaching_response_system` returns the same
  string as before (byte-compare against a snapshot taken pre-refactor).

## 5. Migration safety
This is a literal move: extract each YAML block scalar to a file verbatim, then
delete the `prompts:` block. To guarantee no drift, the implementer will snapshot
all ten prompt strings to a temp file before the move and byte-compare after.

## 6. Out of scope
Editing any prompt's content; per-prompt versioning/AB infrastructure (a later
follow-up the eval harness enables); moving non-prompt constants.

## 7. File map
| File | Change |
|---|---|
| `src/backend/config/prompts/*.md` (10 files) | New — prompt bodies, verbatim |
| `src/backend/config/tunables.yaml` | Remove `prompts:` block |
| `src/backend/config/__init__.py` | `_load_prompts()`, merge into `get_tunables()` |
| `tests/test_config.py` | Prompt-loading assertions |
