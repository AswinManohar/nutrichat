# Contract: chat response (user-facing, unchanged shape)

**Surfaces**: `POST /meals/log` (web), Telegram text handler — both call
`orchestrator.handle_message`, so they behave identically (FR-016).

The response dict keeps exactly its current keys:

```json
{ "status": "success", "message": "...", "paused": false, "items": [], "response_id": "..." }
```

No field is added, removed or renamed. Web and Telegram clients need no change.

## Behaviour changes a client can observe

| Situation | Before | After |
|---|---|---|
| "protein shake", "low fat yogurt", other bare foods with nutrient words | coaching reply | meal card (`paused: true`, `items` filled) |
| Mixed message: "I had pizza, was that bad?" | coaching reply | coaching reply whose `message` ends with `typesafe.log_offer_text` on a new paragraph |
| Pure question: "is pizza healthy?" | coaching reply | coaching reply, no offer appended |
| Free-tier user with 0 credits sends a cue-less question | treated as a meal (quota short-circuit in routing) | routed as coaching; coaching handler returns the existing upgrade message |
| Pending card, or photo attached | card reply / meal logging | unchanged |
| Jev unavailable | n/a | same replies as with Jev, possibly ~0.6 s slower; never an error |

## Offer-to-log text

- Appended by code, not generated: `f"{reply}\n\n{log_offer_text}"`.
- Appended after citation extraction, so `[n]` markers and `citations` are
  unaffected.
- Included in the saved `coaching_response.response_text` and the coaching
  history turn, so the coach sees it was offered.
- Appended to every coaching reply for that turn, including the
  "I don't have data on …" early return, except the upgrade message (no
  coaching happened, so nothing to follow up on).
