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

Where items come from (one source of truth): `pending_entry` and `escalation`
items are derived on read from `profile_entry` (state `pending`) and
`red_flag_escalation`, and have no `review_item` row until a reviewer decides
(the row then stores only the decision). Their `id` is the subject id
(entry or escalation id). `rule_conflict`, `plan_sample` and
`unknown_medication` rows are queued by `agent/suggest.py` and their `id` is
the `review_item` id. `plan_sample` rows are created for the share of shown
recommendations chosen by hashing the recommendation id against
`safety.plan_sample_rate`. `open=false` lists decided items instead (ordered
by when their `review_item` row was created). The escalation list content has
the rule label and time, never the message text.

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

`edit` is required for `edited` and rejected with any other decision (422).
A `rule_conflict` edit retires the conflicting confirmed entries (reason
`replaced`) and creates the clinician `nutrient_limit` (`replaces_id` = the
first conflicting entry), so the conflict no longer exists. A `plan_sample`
rejection needs a non-blank comment; the export (`guidelines/export_feedback`)
writes these as records with `source: "plan_sample"`. The decision route takes
the id from the listing; the response is `{id, kind, decision, decided_by,
decided_at, entry}` where `entry` is the confirmed/created entry, if any.
A pending entry the patient has already settled is 409. All writes of a
decision happen in one transaction.
409 when the item is already decided.

## POST /admin/review/patients/{patient_id}/entries

Reviewer-entered hard entry (for example a clinician-set sodium limit). Created
confirmed, source `clinician`, `created_by` `reviewer:<id>`. Body: `type`,
`value`, optional `label` and `client_request_id`. 404 unknown patient, 409
when the patient's profile is at `hard_profile_max_entries`, 422 invalid value.

`REVIEWER_USER_IDS` is read on every request (comma-separated, case-insensitive);
empty or unset means nobody is a reviewer.
