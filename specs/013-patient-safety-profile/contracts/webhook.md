# Contract: Escalation webhook

Celery task `backend.workers.tasks.notify_escalation(escalation_id)`, enqueued
after the escalation row commits. POST to `SAFETY_WEBHOOK_URL` (Railway
variable), JSON, timeout 5 s, retries with backoff 5 s, 15 s, 45 s, 2 min,
5 min. Status recorded on `red_flag_escalation.notify_status`.

Slack-compatible body (R12: no message text, no name or email):

```json
{
  "text": "Mealsy red flag: Stopped insulin. Patient 3f2c…a91e. Review: https://<api host>/admin/review/escalations/7b1d…",
  "escalation_id": "7b1d…",
  "rule_id": "stopped_insulin",
  "patient_id": "3f2c…a91e",
  "created_at": "2026-11-20T10:00:00Z"
}
```

- 2xx → `sent`. Other status or network error → retry; after the last try →
  `failed` and `logfire.error`.
- `SAFETY_WEBHOOK_URL` unset → `no_recipient` and `logfire.error` on every
  escalation (spec Decisions, Q3).
- The patient's fixed response never waits on this task (US3-5).

Implementation notes:

- One try at once, then one retry after each delay (6 tries in all). Delays and
  the 5 s timeout are `safety.escalation_retry_seconds` and
  `safety.escalation_webhook_timeout_s` in `tunables.yaml`.
- `SAFETY_REVIEW_BASE_URL` unset: the text omits the "Review:" link.
- A row already `sent` is not posted again if the task runs twice.
- Failures log the HTTP status or exception class only, never the webhook URL.
