# Feature Specification: Correct a Wrong Food Match

**Feature Branch**: `003-correct-food-match`

**Created**: 2026-09-28

**Status**: Draft (clarified 2026-09-28)

**Input**: User description: "I want to resolve issue 39, probably a feature" — GitHub issue #39: *"Not the right food?" picker has no search or escape hatch — can't fix a wrong match.* Example from exploratory testing: "2 eggs and toast" resolved toast to *Shrimp toast*; the picker offered only Shrimp toast / Melba toast / Anisette toast, all wrong.

## Context

When a user describes a meal, each food is matched to a reference food and shown on a confirm card. If a match is wrong, the user taps **Not the right food?** Today that offers at most three alternative names, with no nutrition shown, no way to search, and (after a recent stop-gap) only "Describe it differently" (re-asks the assistant) or "None of these — remove it". Every correction goes back through the conversational assistant, takes seconds, and can mis-resolve again. Corrections are never remembered, so the same wrong match recurs on the next log.

This feature makes fixing a wrong match fast and predictable in the Android app. Remembering a user's corrections for future logs is a planned follow-up; this feature records corrections so that follow-up can build on them.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Search for the right food (Priority: P1)

A user sees a wrong match on the confirm card ("Shrimp toast" for "toast"). They tap **Not the right food?**, type "white bread toasted" into a search field (pre-filled with what they originally wrote), see a list of matching foods with calories and protein for the amount on the card, tap the right one, and the card updates in place: new name, same quantity, new nutrition, updated meal totals. The other items on the card are untouched.

**Why this priority**: This is the missing escape hatch. Without it a user facing three wrong alternatives can only delete the item or gamble on the assistant again. It also resolves the root complaint of issue #39.

**Independent Test**: With a pending card that contains a mismatched item, open the picker, search, pick a result, and confirm the card updates and logs the chosen food with the original quantity — without any other item changing.

**Acceptance Scenarios**:

1. **Given** a confirm card with an item "Shrimp toast, 28 g" that the user originally described as "toast", **When** the user opens **Not the right food?**, **Then** a search field is shown pre-filled with "toast" and results appear without further typing.
2. **Given** the search field, **When** the user types "white bread toasted", **Then** matching foods are listed within 1 second, each showing its name and calories + protein for 28 g.
3. **Given** the result list, **When** the user taps "Bread, white, toasted", **Then** the sheet closes, the item shows "Bread, white, toasted · 28 g" with its nutrition, the meal totals update, and a brief confirmation shows which food was swapped.
4. **Given** the item was swapped, **When** the user taps **Confirm & log**, **Then** the logged meal contains the chosen food with the same quantity and the nutrition shown on the card.
5. **Given** a swap was just made, **When** the user taps **Undo** on the confirmation, **Then** the item reverts to the previous match.

---

### User Story 2 - Compare the suggested alternatives (Priority: P2)

Before searching, the user sees the existing suggested alternatives at the top of the picker, each with calories and protein for the amount on the card, so they can tell at a glance which one is closest — and picking one updates the card immediately, without waiting on the assistant.

**Why this priority**: Often the right answer is already among the suggestions; showing numbers makes the choice informed and instant. It removes the multi-second assistant round-trip for the most common correction.

**Independent Test**: Open the picker on any item that has alternatives; verify each alternative shows nutrition for the current quantity and that choosing one updates the card instantly and logs correctly.

**Acceptance Scenarios**:

1. **Given** an item with suggested alternatives, **When** the picker opens, **Then** the current match is marked, and each alternative shows calories and protein for the item's current quantity.
2. **Given** the user taps an alternative, **When** the sheet closes, **Then** the card reflects the new food within 1 second, with no "assistant is typing" wait.

---

### Edge Cases

- **No search results**: show "No foods found for '…'" with the existing fallbacks — "Describe it differently" (assistant re-interprets) and "None of these — remove it".
- **Food reference unavailable** (the external food database is down or slow): search shows a clear, non-blocking message and keeps the fallbacks usable; the card is never left in a broken state.
- **Offline**: search field is disabled with an "You're offline" note; removing the item still works.
- **Very short or empty query** (< 2 characters): no search is run; suggestions stay visible.
- **Item is an estimate** (no reference match, nutrition estimated): the picker still offers search so the user can replace the estimate with a real reference food.
- **Composite dish items** (e.g. a sandwich decomposed into parts): searching replaces only the selected part.
- **Quantity**: swapping keeps the item's quantity in grams; if the chosen food is typically measured per piece, the grams are kept and the user can adjust with the existing stepper.
- **Picking the same food as current**: no change and no confirmation toast.
- **Card already logged or discarded**: the picker is not available.
- **Rapid typing**: only the latest query's results are shown; stale results never overwrite newer ones.

## Clarifications

### Session 2026-09-28

- Q: Is remembering corrections part of this feature? → A: No, it's a follow-up feature. This feature only records corrections (FR-012).
- Q: Which apps get the new picker? → A: Android only. The web app is unchanged (FR-010).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to search the food reference by free text from the **Not the right food?** picker on any unlogged confirm-card item.
- **FR-002**: The search field MUST be pre-filled with the phrase the user originally used for that item, and results for it MUST appear on open.
- **FR-003**: Each search result and each suggested alternative MUST show the food name plus calories and protein scaled to the item's current quantity.
- **FR-004**: Selecting a result or alternative MUST replace only that item on the card — keeping its quantity and meal type — and immediately update the item's nutrition and the meal totals, without a conversational round-trip.
- **FR-005**: The logged meal MUST contain exactly the food and nutrition shown on the card at confirm time.
- **FR-006**: After a swap the app MUST show a brief confirmation naming the new food, with an Undo that restores the previous match.
- **FR-007**: The picker MUST keep the existing fallbacks: "Describe it differently" and "None of these — remove it".
- **FR-008**: The picker MUST handle no results, slow/unavailable reference data and offline state with clear messages, never blocking the fallbacks or corrupting the card.
- **FR-009**: Search results MUST be relevant to the query, ranking generic foods ahead of branded products and dishes that add ingredients the user didn't mention.
- **FR-010**: The new picker experience MUST ship in the Android app. The web app's existing "Not the right food?" list is unchanged by this feature.
- **FR-011**: The picker MUST be fully usable with a screen reader: the search field is labelled, each result announces name and nutrition, and the current match is announced as selected.
- **FR-012**: The system MUST record each correction (original phrase, previous match, chosen food) so wrong-match patterns can be reviewed to improve matching for everyone, and so a future "remember my corrections" feature can use them. Recorded corrections MUST NOT change how future meals are matched in this feature.

### Key Entities

- **Confirm-card item**: one food on an unlogged meal — the user's original phrase, the matched food, quantity, nutrition, whether it is an estimate, and its alternatives.
- **Food reference entry**: a food from the reference database — name, category (generic vs branded), and nutrition per 100 g.
- **Correction record**: user, original phrase, previously matched food, chosen food, time. Used for reviewing and improving matching (FR-012), and by the planned follow-up that remembers corrections.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can replace a wrong match with the right food in under 10 seconds and no more than 3 taps plus typing, from opening the picker to seeing the updated card.
- **SC-002**: Swapping to a suggested alternative or search result updates the card in under 1 second (vs. several seconds today through the assistant).
- **SC-003**: Search returns results within 1 second for 95% of queries.
- **SC-004**: For the known problem phrases (toast, fries, oats, chai, dosa and the existing food-matching regression set), the correct food appears in the top 5 search results at least 90% of the time.
- **SC-005**: Items removed via "None of these — remove it" after opening the picker drop by at least 50% versus the pre-feature baseline, indicating users find the right food instead of giving up.

## Assumptions

- The existing food reference (USDA FoodData Central, including the local copy already used for matching) is the search source; no new third-party food database is introduced.
- Quantity is carried over in grams on swap; portion-unit conversion is not part of this feature.
- Search uses the same matching improvements already in place (e.g. treating "toast" as toasted bread), so results for problem phrases improve alongside suggestions.
- The existing "Describe it differently" and "None of these — remove it" fallbacks (added as a stop-gap on the Android branch) remain.
- Logging uses the card as shown; no re-interpretation by the assistant happens at confirm time.
- Correction records (FR-012) are stored with the user's other meal data and deleted with their account under the existing account-deletion flow.
- Out of scope (planned follow-ups): remembering a user's corrections and applying them to future logs ("your usual" matches with a Forget control); the same picker in the web app.
- Out of scope: adding custom foods with manually entered nutrition ("My Foods"), barcode scanning, and changing how the assistant parses the initial message.
