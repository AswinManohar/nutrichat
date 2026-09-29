# Quickstart: validating "Correct a Wrong Food Match"

The work happens on branch `feat/android-app` in the worktree `~/nutrichat-android`. Contract details are in [contracts/foods-api.md](contracts/foods-api.md) and [contracts/android-picker-ui.md](contracts/android-picker-ui.md), and the data shapes are in [data-model.md](data-model.md).

## Prerequisites

- The matcher port (#51) is on the branch: `git -C ~/nutrichat-android log --oneline | grep -E "rank generic FDC|176-case|toast"` lists all three commits, and the food-identity eval reports ≥ 156/177.
- Migration `015_food_correction` is applied to the target DB. Local: `alembic upgrade head`. Prod is applied manually through Supabase, as for earlier migrations.
- The backend is running: `uvicorn backend.main:app --app-dir src --port 8000` from `~/nutrichat-android`.
- Emulator and debug APK as in the Android test notes (debug cleartext to `10.0.2.2` is already committed).

## 1. Backend search (Story 1, FR-001/003/009, SC-003/004)

```bash
TOKEN=...   # a signed-in user's access token
curl -s "localhost:8000/foods/search?q=toast&qty_g=28" -H "Authorization: Bearer $TOKEN" | jq '.results[:5][] | .name'
```

Expected: a toasted-bread entry ranks above "Shrimp toast", and each result carries `kcal` and `protein_g` for 28 g.

```bash
curl -s -o /dev/null -w "%{http_code}\n" "localhost:8000/foods/search?q=t" -H "Authorization: Bearer $TOKEN"   # 422
```

Search-quality gate: run the offline food-identity eval in search mode. The correct food must be in the top 5 for ≥ 90% of cases (SC-004). Baseline at implementation: 164/178 = 92.1%.

```bash
cd ~/nutrichat-android && PYTHONPATH=src uv run python eval/food_identity_search.py
```

## 2. Build a swapped item (FR-004/005)

```bash
curl -s "localhost:8000/foods/172687?qty_g=28" -H "Authorization: Bearer $TOKEN" | jq '{food_name, qty_g, kcal, estimated}'
```

Expected: the item is scaled to 28 g, with `estimated: false`.

## 3. Log with a correction, and check that the pending card is resolved (FR-012, R4)

1. In the app, send "2 eggs and toast" and wait for the confirm card.
2. `GET /meals/pending?conversation_id=…` returns the card.
3. Swap the toast item through search, then **Confirm & log**.
4. `GET /meals/pending?conversation_id=…` now returns no card.
5. SQL: `select original_phrase, from_name, to_name, method from food_correction order by created_at desc limit 1;` gives `toast | Shrimp toast | Bread, white, … toasted | search`.
6. Swap then Undo, then log: no new `food_correction` row.

## 4. Android picker (Stories 1–2, FR-002/006/007/008/011)

1. Tap **Not the right food?** on the toast item. The field shows "toast" and results appear without typing.
2. Suggestions show kcal and protein for the item's grams, and the current match is checked.
3. Type "white bread toasted". Results update after typing stops, and fast typing never shows stale results.
4. Pick a result. The sheet closes within about 1 s, the item and totals update, and the "Swapped to …" toast with Undo appears.
5. Undo restores the original item.
6. Airplane mode, then reopen the picker: the field is disabled with "You're offline", and "None of these — remove it" still works.
7. Stop the backend's local DB (set `USDA_DB_PATH=/nonexistent`, restart): "Can't search right now" appears, and the fallbacks still work.
8. TalkBack on: the field is announced as "Search foods", and rows read name + kcal + protein (+ "selected").

## 5. Automated gates

```bash
cd ~/nutrichat-android && PYTHONPATH=src uv run python -m pytest tests/ -k "foods or log_items or corrections or usda" -q
cd android && ./gradlew ktlintCheck testDebugUnitTest :core:domain:test verifyRoborazziDebug :app:lintDebug
```

Everything passes, apart from the pre-existing `test_chat_history_isolation` 401 failure.
