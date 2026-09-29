# Contract: "Not the right food?" picker (Android)

This is the user-facing contract for the redesigned bottom sheet (`CandidatePickerSheetContent`). It replaces the current three-name list. The web app is unchanged (FR-010).

## Layout (top → bottom)

1. **Title**: "Pick the right food". Subtitle: "Currently: {matched name}".
2. **Search field** (`PillInput`), labelled "Search foods" for TalkBack. Pre-filled with the item's original phrase (FR-002), with a clear button. It's disabled with "You're offline" when there's no connection.
3. **Suggestions** section (only if `candidate_details` is non-empty): one row per alternative with its name and "{kcal} kcal · {protein} g protein" for the item's current grams. The current match shows a check and reads as "selected" to TalkBack (FR-011).
4. **Results** section: the search results in the same row format, best first. Only the latest query's results are ever shown (stale requests are cancelled).
   - While loading: row-shaped skeletons (no spinner).
   - Empty: "No foods found for '{q}'".
   - Error or 503: "Can't search right now". Suggestions and fallbacks stay usable.
5. **Fallbacks** (always present, FR-007): "Describe it differently" (existing chat path) and "None of these — remove it" (existing local remove with Undo).

## Interactions

| Action | Result |
|---|---|
| Type ≥ 2 chars | Search runs 250 ms after typing stops. Fewer than 2 chars shows suggestions only |
| Tap a suggestion or result | The row shows a pressed state and the sheet closes when the item arrives from `GET /foods/{fdc_id}`. Target < 1 s (SC-002). The card item updates in place, keeping its grams and meal type; totals animate |
| Swap succeeds | InkToast "Swapped to {name}" with **Undo** (FR-006), plus a light confirm haptic |
| Swap fails | Sheet stays open with an inline message "Couldn't switch foods. Try again." The card is unchanged |
| Tap the current match | No-op, closes the sheet, no toast |
| Undo | Restores the previous item exactly, drops that item's pending correction |
| Confirm & log | The item is logged with `correction` (see foods-api.md) |

## Accessibility (FR-011)

- Search field: `contentDescription` "Search foods", IME action Search.
- Each row is one merged node that reads "{name}, {kcal} kilocalories, {protein} grams protein" (plus ", selected" for the current match), with role Button and a 48 dp minimum height.
- A result-count change is announced politely ("{n} results").
