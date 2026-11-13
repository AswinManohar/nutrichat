# Contract: Review queue (admin, backend only)

Router `api/review.py`, prefix `/admin/review`. Dependency
`auth/reviewer.py::require_reviewer`: valid Supabase JWT and the caller's user
id in `REVIEWER_USER_IDS`; otherwise 403. Every decision records
`reviewer:<user id>` as the actor. No screen is built (spec Decisions, Q1).

## GET /admin/review/items?kind=&open=true&limit=50&before=

Newest first, filterable by `kind` (`pending_entry`, `rule_conflict`,
`escalation`, `plan_sample`, `unknown_medication`).

```json
{
  "items": [
    {
      "id": "uuid", "kind": "pending_entry", "patient_id": "uuid",
      "created_at": "…",
      "content": {"type": "allergy", "label": "Shellfish allergy", "evidence": "I found out I'm allergic to shellfish"}
    }
  ],
  "next_before": "…"
}
```

Patients are identified by id only (FR-040c).

## GET /admin/review/escalations/{id}

Escalation with the message text, rule, notification status. The webhook links
here (R12).

## POST /admin/review/items/{id}/decision

```json
{"decision": "approved" | "rejected" | "edited" | "handled",
 "edit": {"type": "nutrient_limit", "value": {...}, "label": "…"} ,
 "comment": "…"}
```

| Kind | approved | rejected | edited | handled |
|---|---|---|---|---|
| pending_entry | entry → confirmed, `confirmed_by=reviewer:…` | entry → retired | old retired, new confirmed entry, source `clinician`, `replaces_id` | 422 |
| rule_conflict | 422 | 422 | `edit` required: new confirmed clinician `nutrient_limit` that resolves it | 422 |
| escalation | 422 | 422 | 422 | stored decision + date |
| plan_sample | comment stored | comment required, stored for eval export | 422 | 422 |
| unknown_medication | 422 | 422 | 422 | handled (reviewer added a table rule or noted none) |

409 when the item is already decided.

## POST /admin/review/patients/{patient_id}/entries

Reviewer-entered hard entry (for example a clinician-set sodium limit). Created
confirmed, source `clinician`.
