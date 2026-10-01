# Feature Specification: Edit Saved Meals

**Feature Branch**: `006-edit-saved-meals` (spec directory; no git branch created yet)

**Created**: 2026-10-01

**Status**: Draft

**Input**: User description: "I want to implement a feature so that the saved meals can be edited."

## Background

Users can save a meal from the chat confirmation card to My Meals. Next time
they mention it by name, the app fills the card from the saved meal, so they
get the same ingredients and numbers.

Today a saved meal can't be changed after it is saved. To fix a wrong
ingredient, a wrong amount or a bad name, the user has to delete the meal and
save it again from a new chat card. The two apps also save different things:

- **Android** saves the card as edited: removed items are left out, and changed
  amounts and the portion size are kept.
- **Web** saves the card as it was first shown, before any edits. Users who
  fixed the card before saving get the uncorrected version back next time.

Changes made when logging a saved meal (on the My Meals "Customize" screen, or
on the chat card) apply to that one log only. They never update the saved
meal.

## Clarifications

### Session 2026-10-01

- Q: When a user swaps an ingredient in a saved meal, what should the language-model call return? → A: One structured replacement food: a database-style name, grams, original unit, and whether the user stated an amount. Its nutrition comes from the same nutrition-database lookup as chat logging. The model estimates nutrition only when the lookup finds no match.
- Q: Should a swap's language-model call use up a usage credit? → A: Yes, 1 credit per swap, charged through the same shared usage check as chat logging. Credits are a placeholder that will change with the future subscription model, so the swap must not carry its own quota rules.
- Q: Should adding a new ingredient use the same language-model call as swapping? → A: Yes. Adding uses the same structured call and output, and costs 1 usage, the same as a swap. When no amount is stated, the model's typical portion is used.
- Q: Besides the user's text, what context should the model get when it produces the structured food? → A: For a swap, the ingredient being replaced (name, grams, unit) and the meal name. For an add, only the meal name. It never gets the other ingredients.
- Q: What accuracy bar must the swap/add model call reach on an offline eval set before it ships? → A: At least 90% correct, where correct means the right food and grams within ±25% of the reference. Measured on at least 40 cases covering swaps and adds, run live 5 times like the routing gate. Nutrition match is tracked as a separate metric.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Edit a saved meal from My Meals (Priority: P1)

A user opens My Meals, picks a saved meal and edits it. They can rename it,
change how much of each ingredient it contains, and remove ingredients. They
see the meal's calories and macros update as they edit, then save. After that,
both logging from My Meals and mentioning the meal in chat use the edited
version.

**Why this priority**: This is the core request. Without it, the only way to
fix a saved meal is to delete it and rebuild it from chat.

**Independent Test**: Save a meal with three ingredients. Open it in My Meals,
change one ingredient's amount, remove another, rename the meal and save. Then
quick-log it, and also type its new name in chat. Both must show the two
remaining ingredients at the edited amounts under the new name.

**Acceptance Scenarios**:

1. **Given** a saved meal "Chicken biryani" with rice 200 g, chicken 150 g and
   raita 100 g, **When** the user changes rice to 150 g and saves, **Then** the
   saved meal shows rice 150 g, and its calories and macros are recalculated
   from the new amount.
2. **Given** the same saved meal, **When** the user removes raita and saves,
   **Then** the saved meal lists only rice and chicken, and its totals no longer
   include raita.
3. **Given** the same saved meal, **When** the user renames it to "Biryani" and
   saves, **Then** typing "had biryani for lunch" in chat brings up the saved
   meal, and the old name "chicken biryani" no longer does.
4. **Given** the user is part way through editing, **When** they cancel or
   leave the screen without saving, **Then** the saved meal is unchanged.
5. **Given** the user edits a saved meal, **When** they save, **Then** meals
   they already logged from it keep the values they were logged with.

---

### User Story 2 - Saving from chat keeps the user's edits on every app (Priority: P1)

A user corrects the chat card by changing amounts, removing items or setting a
portion size, and then saves it to My Meals. The saved meal matches what they
see on the card, on both web and Android.

**Why this priority**: Without this, editing in My Meals only fixes the
mistakes that saving from chat keeps creating on web. It is also the specific
gap the user reported ("does the saved meal retain the user changed values").

**Independent Test**: On web, describe a meal, change one item's grams on the
card, remove another item, set portion to 1.5×, and save as a meal. Open it in
My Meals. It must match the card's final items, amounts and totals. Repeat on
Android with the same result.

**Acceptance Scenarios**:

1. **Given** a chat card with rice 200 g that the user changed to 150 g,
   **When** they save it as a meal, **Then** the saved meal has rice 150 g, with
   nutrition values for 150 g.
2. **Given** a chat card where the user removed an item, **When** they save it
   as a meal, **Then** the saved meal leaves that item out.
3. **Given** a chat card with portion set to 1.5×, **When** they save it as a
   meal, **Then** each saved ingredient's amount and nutrition is 1.5× the
   card's base value, and the saved meal logs at 1× afterwards.
4. **Given** the same card edits made on web and on Android, **When** each is
   saved, **Then** the two saved meals have the same ingredients, amounts and
   totals.

---

### User Story 3 - Update a saved meal from a changed log (Priority: P2)

A user mentions a saved meal in chat, or logs it from My Meals with Customize,
and changes it while logging (for example, less rice). After logging, they are
offered to also update the saved meal with these changes. If they accept, the
saved meal changes. If they don't, only that one log is changed.

**Why this priority**: Users find out a saved meal is wrong when they log it.
Letting them fix it right there saves a trip to My Meals. It comes after P1
because the P1 edit screen already allows the fix.

**Independent Test**: Mention a saved meal in chat, reduce one ingredient on
the card, log it and accept "Update saved meal". The next mention brings back
the reduced amount. Repeat but decline: the next mention brings back the
original amount.

**Acceptance Scenarios**:

1. **Given** a card filled from saved meal "Oats bowl" with the user's changes,
   **When** they log it and accept updating the saved meal, **Then** the saved
   meal now holds the card's final ingredients and amounts.
2. **Given** the same situation, **When** the user declines or ignores the
   offer, **Then** the saved meal is unchanged and only that log reflects the
   changes.
3. **Given** a card filled from a saved meal with no changes, **When** the user
   logs it, **Then** no update offer is shown.
4. **Given** a log from My Meals Customize with changed amounts or removed
   ingredients, **When** it is logged, **Then** the same update offer is shown.

---

### User Story 4 - Add or swap ingredients in a saved meal (Priority: P3)

While editing a saved meal, the user adds a missing ingredient ("add 1 tbsp
ghee") or replaces one with a different food ("use brown rice instead of white
rice"). The new food is looked up the same way foods are looked up when
logging.

**Why this priority**: Changing amounts and removing items covers most fixes.
Adding and swapping need a food lookup inside the edit screen, which is more
work and less often needed.

**Independent Test**: Edit a saved meal, add "ghee 10 g", swap "white rice" for
"brown rice" and save. Then log the meal. The card shows ghee and brown rice,
with nutrition values for those foods.

**Acceptance Scenarios**:

1. **Given** a saved meal being edited, **When** the user adds "1 tbsp ghee",
   **Then** a ghee row appears at the grams for 1 tbsp, with its nutrition,
   and is included in the meal totals. Typing just "ghee" uses a typical
   portion instead.
2. **Given** a saved meal being edited, **When** the user swaps "white rice
   150 g" by typing "brown rice", **Then** that row becomes brown rice at
   150 g with brown rice's nutrition, and every other row is unchanged. Typing
   just "brown" gives the same result.
3. **Given** the same swap, **When** the user types "1 cup brown rice",
   **Then** the row becomes brown rice at the grams for 1 cup, because the
   user stated an amount.
4. **Given** the lookup can only produce an estimate for an added or swapped
   food, **When** it is shown, **Then** it is marked as an estimate, the same
   way chat cards mark estimates.

---

### Edge Cases

- **Name clash**: renaming a saved meal to the name of another saved meal the
  user owns is rejected with a clear message. Names count as the same if they
  differ only in case, spacing or punctuation. Renaming a meal to its own name
  with different capitalization is allowed.
- **Empty name**: a name that is blank, or has no letters or digits after
  normalizing, is rejected.
- **Last ingredient**: the user can't remove the last ingredient. A saved meal
  needs at least one. To get rid of the whole meal, they delete it.
- **Invalid amount**: zero, negative or non-numeric amounts are rejected for
  that ingredient, and the user can't save until it is fixed.
- **Unknown nutrients**: an ingredient whose fibre or other nutrients were
  unknown keeps them unknown when its amount is scaled. Scaling must not turn
  them into 0.
- **Edited elsewhere**: if the meal was changed or deleted on another device
  after the user opened it, their save must not silently overwrite or revive
  it. They are told it changed and shown the current version.
- **Deleted meal**: editing a meal that has since been deleted fails with a
  "meal no longer exists" message, and the meal doesn't come back.
- **Logged today**: editing a meal that was already logged today doesn't change
  today's totals. The "logged today" marker on My Meals still matches if the
  meal was renamed.
- **Saving fails**: the user's edits stay on screen with an error and a way to
  retry. Nothing is lost silently.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to open any of their saved meals in an edit
  view, on web and Android.
- **FR-002**: In the edit view, users MUST be able to rename the meal, change
  the amount in grams of any ingredient, and remove any ingredient except the
  last one.
- **FR-003**: The edit view MUST show live totals for calories, protein, carbs,
  fat and fibre that reflect the current edits before saving.
- **FR-004**: Changing an ingredient's amount MUST scale all of its stored
  nutrition values by the same ratio. Nutrients that were unknown MUST stay
  unknown.
- **FR-005**: Edits MUST take effect only when the user saves explicitly.
  Cancelling or leaving the screen MUST discard them.
- **FR-006**: After saving, every way of using the meal MUST use the edited
  version: quick-log, Customize, and recall by name in chat.
- **FR-007**: After a rename, chat recall MUST match the new name and MUST NOT
  match the old one.
- **FR-008**: Renames MUST follow the same name-uniqueness and non-empty rules
  as saving a new meal.
- **FR-009**: Editing a saved meal MUST NOT change any meal already logged from
  it, or the user's past daily totals.
- **FR-010**: Saving a chat card to My Meals MUST save the card exactly as the
  user last saw it: removed items left out, edited amounts kept, and the
  portion multiplier applied to the saved amounts and nutrition. Web and
  Android MUST behave the same.
- **FR-011**: When a meal filled from a saved meal is logged with changes to
  its ingredients or amounts, the system MUST offer to update the saved meal.
  It MUST update the saved meal only if the user accepts.
- **FR-012**: The update offer MUST NOT appear when the logged meal matches the
  saved meal, or when the only change is the portion multiplier or meal type.
- **FR-013**: Users MUST be able to add a new ingredient while editing a saved
  meal by describing it in their own words (for example "1 tbsp ghee"). Adding
  MUST use the same structured language-model call, nutrition lookup, estimate
  fallback, failure handling (FR-014a) and usage counting (FR-014b) as a swap.
  When the user states no amount, the model's typical portion for that food is
  used. The added row appears at the end of the meal. For an add, the model
  receives only the user's text and the meal name.
- **FR-014**: Users MUST be able to swap an ingredient for a different food
  while editing a saved meal by describing the replacement in their own words
  (for example "brown rice", or "2 slices of sourdough"). A language model
  MUST turn the description into exactly one structured food: a
  database-style name, an amount in grams, the original unit, and whether the
  user stated an amount. Only the swapped row may change. Along with the
  user's text, the model MUST receive the ingredient being replaced (name,
  grams, unit) and the meal name, and nothing about the other ingredients. This
  is so that relative phrasing such as "brown" or "whole wheat version"
  resolves against the original food. The new food keeps
  the old ingredient's grams unless the user stated an amount. Its nutrition
  MUST come from the same nutrition-database lookup used in chat logging, with
  a model estimate (marked as one, FR-015) only when no match is found.
- **FR-014a**: When the model's output for a swap is missing, malformed or
  describes more than one food, the swap MUST fail with a message asking the
  user to rephrase. The ingredient MUST stay unchanged.
- **FR-014b**: Each swap MUST count as one usage through the same shared usage
  check that chat logging uses, and MUST NOT have its own quota logic. When the
  user has no usage left, the swap MUST be blocked with the same upgrade
  message as chat, and the ingredient MUST stay unchanged.
- **FR-015**: Ingredients whose nutrition is an estimate rather than a database
  match MUST stay marked as estimates in the edit view and after saving.
- **FR-016**: A save MUST be rejected if the meal changed or was deleted after
  the user opened it. The user MUST be told and shown the current version.
- **FR-017**: Only the meal's owner can view or edit it. Trying to edit another
  user's meal MUST behave as if the meal does not exist.
- **FR-018**: A failed save MUST keep the user's edits on screen with an error
  and a way to retry.

### Key Entities

- **Saved Meal**: a user's named, reusable meal. It has a display name, a
  normalized name used for matching and uniqueness, an ordered list of
  ingredients, totals for calories, protein, carbs, fat and fibre, and when it
  was created and last changed. It belongs to exactly one user. An edit
  replaces its name and/or ingredients and recalculates its totals.
- **Saved Ingredient**: one food in a saved meal. It has the food name, amount
  in grams, nutrition values for that amount (some may be unknown), its source
  (database match or estimate), and any alternative matches. It has the same
  shape as an item on a logged meal, so logging from a saved meal works the
  same as any other log.
- **Logged Meal**: a record of a meal the user ate. It is created from a saved
  meal by copying its values, and it is not linked to later changes in that
  saved meal.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can change one ingredient's amount in a saved meal and
  save in under 30 seconds and at most 4 taps or clicks after opening My
  Meals.
- **SC-002**: In 100% of test cases, the next recall in chat or quick-log after
  an edit shows the edited ingredients, amounts and name, with totals equal to
  those shown when the edit was saved (within ±1 kcal and ±0.1 g, allowing for
  rounding).
- **SC-003**: For the same set of card edits, web and Android produce saved
  meals with the same ingredients, amounts and totals in 100% of test cases.
- **SC-004**: No meal logged before an edit changes its values afterwards. All
  past daily totals stay the same in 100% of test cases.
- **SC-005**: The workaround of deleting and re-saving a meal to fix it drops
  to near zero (under 5% of the deletions seen before launch) within 30 days of
  launch.
- **SC-006**: When the update offer is shown after a changed log of a saved
  meal, at least 30% of users accept it. This shows the offer appears when it
  is useful and isn't seen as noise.
- **SC-007**: Before release, the structured swap/add step produces the right
  food, with grams within ±25% of the reference amount, in at least 90% of
  cases. Measured on an evaluation set of at least 40 cases covering swaps
  (including relative phrasing such as "brown"), adds with and without a
  stated amount, and foods the nutrition database doesn't contain. It is run
  live 5 times and the pass rate averaged. How often the matched nutrition
  equals the reference food's is reported alongside as a separate,
  non-gating metric.

## Assumptions

- Both clients get the edit view: the web app (My Meals page) and the Android
  app (My Meals screen). The Telegram bot is out of scope. It can recall saved
  meals but has no place to manage them.
- A saved meal keeps only its latest version. There is no edit history or undo
  after saving in this version.
- The portion multiplier is a setting for each log, not part of a saved meal.
  Saving from a card applies the portion to the stored amounts (FR-010), and
  the saved meal then logs at 1×.
- Recall by name keeps its current behavior: the meal name has to appear as a
  phrase in the message. Fuzzy or semantic matching is out of scope.
- The update offer (US3) is a choice the user makes. Saved meals never change
  automatically from a log.
- Adding and swapping ingredients (US4) share one language-model call that
  returns one structured food. Nutrition then comes from the database lookup,
  with an estimate as the fallback (FR-013, FR-014).
- The "Update saved meal" offer (US3) saves the card's ingredients and amounts
  at 1×, without the portion multiplier. A portion change describes how much
  was eaten that time, not a change to the meal itself.
- Saved meals are rare, user-owned records. Simple "last saved version wins,
  with a check that the meal hasn't changed since it was opened" is enough. No
  real-time multi-device sync is needed.
- Feature 002 (reusing previously logged meals) is a separate feature. A saved
  meal still takes priority over a past log (002 FR-011). Editing a saved meal
  doesn't change remembered past logs.
