# Card-native confirm/cancel — no chat round-trip

**Date:** 2026-07-08
**Status:** Approved (Approach B)

## Problem

Confirming a meal from the confirmation card today sends a literal `"yes"`
chat message: a user bubble appears, the paused LangGraph thread resumes
(2× `aget_state`, `aupdate_state`, `ainvoke`, per-node checkpoint writes),
and the reply arrives as an agent bubble. Cancel behaves the same way with
a visible `"cancel"` bubble. The card is the UI for the decision; the chat
transcript should not re-narrate it.

Meanwhile "confirm with local edits" already takes a direct path:
`POST /meals/log-items` → no graph, no user bubble, card collapses to the
"✓ Logged: … · N kcal" line, Undo pill arms, and the LLM-generated comment
shows as an agent bubble. Plain confirm is the only case still doing the
chat round-trip.

## Decision

Route **every** card confirm through the existing `/meals/log-items` direct
path. Make cancel silent. Frontend-only; backend and Telegram unchanged.

### Confirm

`ConfirmationCard.handlePrimary` drops the `onAction('yes', mealType)`
branch. With no pending swaps, confirm always calls
`onConfirmLog(finalItems, mealType, portion)` — identical for edited and
unedited cards. Result (all existing `logItemsDirect` behavior):

- no user bubble;
- card collapses to `✓ Logged: <label> · <kcal> kcal`;
- the `/log-items` response `message` (LLM comment from
  `_generate_log_reply`) renders as an agent bubble;
- `lastLoggedMealId` arms the 30 s Undo pill;
- `conversationId` resets; the paused graph thread is orphaned
  (same accepted pattern as card dismissal).

Swap corrections (`use X instead of Y`) keep the chat path unchanged —
they need LLM re-resolution and their user bubble carries real information.

### Cancel

New store action `cancelCard()`:

1. Stamps the last interactive card `resolved: 'discarded'` and clears
   `conversationId` immediately (optimistic — the UI never waits).
2. Fire-and-forget `POST /meals/log` with `user_input: "cancel"` on the old
   thread id so the graph reaches its cancel node and the checkpoint closes
   cleanly. The response is ignored; errors are swallowed (worst case: an
   orphaned thread, which is already acceptable).

No user bubble, no "Cancelled. No meal logged." agent bubble.

### Store / rendering changes

- `ChatMessage.resolved: 'logged' | 'discarded'`.
- `stampLoggedCard` generalizes to
  `stampResolvedCard(messages, kind, explicit?)`.
- `CollapsedCard` gains a discarded variant: muted
  "Discarded — nothing logged." line, no check icon, no kcal.
- `handleDismissCard` (all items removed) switches from morphing the
  message into a text bubble to the same `resolved: 'discarded'` stamp.

## Out of scope

- Backend changes of any kind. `_generate_log_reply` stays (its output is
  the comment bubble, returned by `/log-items`).
- Telegram: still confirms by typing "yes"; unchanged.
- Suppressing bubbles for swap corrections or add-ingredient actions.

## Error handling

- `/log-items` failure: existing `logItemsDirect` catch shows the
  "Couldn't log that…" agent bubble; card stays interactive (not stamped).
- `cancelCard` backend failure: ignored; card is already discarded locally.

## Testing

- Existing `tests/test_log_items.py` covers the endpoint (unchanged).
- Manual verification in the running app: plain confirm, edited confirm,
  swap → new card → confirm, cancel, all-items-removed dismiss, undo after
  a card confirm. Confirm no `"yes"`/`"cancel"` user bubbles appear and the
  Undo pill still works.
