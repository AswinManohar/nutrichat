# Quickstart: Validate Edit Saved Meals

**Prerequisites**:
- The backend runs locally: `uvicorn backend.main:app --reload --port 8000`
  with `PYTHONPATH=src`.
- Web: `cd frontend && npm run dev`.
- Android: emulator recipe in project memory (`android-emulator-testing`).
  Local backend → **prod DB**, so use a test account only.
- No migration to run.

API shapes are in [contracts/my-meals-api.md](contracts/my-meals-api.md).
Field rules are in [data-model.md](data-model.md).

## Automated

```bash
PYTHONPATH=src pytest tests/test_my_meals_api.py tests/test_my_meals_graph.py \
    tests/test_my_meals_log.py tests/test_my_meals_match.py -q
cd frontend && npm test -- my-meal
cd android && ./gradlew :core:domain:test :core:data:test
```

The tests must cover:
- `PUT` happy path, totals recomputed.
- Unknown fibre stays `null` after scaling.
- 409 `name_taken`.
- 409 `meal_changed` with `current` in the body.
- 404 for a deleted or another user's meal.
- 422 for an empty name or zero grams.
- `POST` with `target_qty_g`+`portion`.
- A recall after a rename hits the new name and misses the old one.
- `flags.saved_meal_id` is written on all three log paths, and `logged_today`
  survives a rename.
- Web save-from-card sends `finalItems` and `portion`.
- `EditMealState` dirty/valid rules.
- `resolve-ingredient` with the LLM mocked:
  - one food → 200;
  - 0 or 2 foods → 422 `rephrase`;
  - credit refused → 402 and the LLM is not called;
  - LLM timeout → 503;
  - the grams rule (a swap without an amount keeps the old grams);
  - the estimate fallback carries `estimated=true`.

## Eval gate (SC-007), live and costs Gemini calls but no user credits

```bash
uv run --env-file .env python eval/gate.py --only ingredient_replace --runs 5
```

Expected: the mean pass rate is ≥ 90% (absolute floor). Nutrition match
(`fdc_id` in `expect_fdc_ids`) is reported, not gated. The first passing run
is saved as `eval/baseline_ingredient_replace.json`. Case format and mix are in
[research R10](research.md#r10-offline-eval-sc-007).

## Manual scenarios (web, then Android)

| # | Steps | Expected |
|---|---|---|
| 1 (US1) | Save "chicken biryani" (rice 200 g, chicken 150 g, raita 100 g). In My Meals → Edit, set rice to 150 g, remove raita, rename it "Biryani", Save. | The list shows "Biryani", 2 items, and totals that match the editor's live totals. |
| 2 (US1) | In chat, type "had biryani for lunch". | The card shows rice 150 g + chicken 150 g. "chicken biryani" alone no longer recalls it. |
| 3 (US1) | Edit, change grams, then Cancel or go back. | The meal is unchanged. |
| 4 (US1/FR-009) | Note today's totals, edit a meal you already logged today, then reload. | Today's totals are unchanged. The meal still shows "logged today" after a rename. |
| 5 (US2) | On a fresh card, change grams on one item, remove one, set the portion to 1.5×, and Save as meal. | The saved meal has only the kept items, at the edited grams × 1.5. Doing the same on Android gives identical numbers. |
| 6 (US3) | Recall a saved meal in chat, reduce one item, Log, accept "Update in My Meals". | The next recall shows the reduced grams. Repeat with the portion changed only: no offer appears. |
| 7 (US3) | Same as 6 but decline. | The saved meal is unchanged. |
| 8 (US4) | Edit, swap white rice 150 g by typing "brown". Then add "1 tbsp ghee", then Save. | Rice becomes brown rice at 150 g, and the other rows are unchanged. Ghee is added at about 13 g. Totals update. The usage counter goes up by 2. |
| 8b (US4) | Swap by typing "rice and dal", then "asdf". | Both show "Describe one food…", and the row is unchanged. |
| 8c (US4/FR-014b) | Set a test user's quota to exhausted, then swap. | The upgrade message is shown, the row is unchanged, and no LLM span appears in Logfire. |
| 8d (US4/FR-015) | Swap to a food the database doesn't have (e.g. a regional dish). | The row shows the estimate marker. After Save and recall it is still marked as an estimate. |
| 9 (FR-016) | Open the editor on web, edit and save the same meal on Android, then save on web. | Web shows "changed on another device" and reloads the latest version. Nothing is overwritten. |
| 10 (FR-018) | Turn off the network, then Save. | The edits stay, with an error and Retry. |

## Observability check

- The Logfire spans for `PUT /my-meals/{id}` should show the status code. A
  `meal_changed` 409 should appear as a handled response, not an exception.
- The `resolve_ingredient` span records `mode`, `n_foods`, `amount_stated`,
  `source`, `estimated` and `latency_ms`. Over the manual run, p95 should be
  ≤ 3 s.
