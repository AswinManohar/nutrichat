# Quickstart: validating the move to GLiDE

**Contract**: [contracts/glide-routing-request.md](contracts/glide-routing-request.md)
· **Data model**: [data-model.md](data-model.md)

Prerequisites: branch `009-migrate-jev-to-glide`, `FASTINO_API_KEY` in the
local `.env` (never committed). All commands send canned or eval-set strings
only, never user data.

## 1. The API accepts our request (before any code changes)

```bash
set -a && . ./.env && set +a
uv run python eval/probe_glide.py --check
```

Expected: HTTP 200, `model: glide`, three answers. Records whether the nested
`intent` criteria are accepted and which model spelling works. A `422` here
means flattening the criteria (research R2) before anything else.

## 2. Unit tests, offline

```bash
DATABASE_URL=postgresql+asyncpg://nutrichat:nutrichat@127.0.0.1:5411/<throwaway> \
  uv run pytest
```

Expected: all pass except the known offline failure
`test_e2e_meals.py::test_chat_history_isolation`. `tests/test_system_one.py`
covers: success, each failure reason, no key, malformed answer, the holdout
rule, and that no log line contains message text.

## 3. Routing accuracy (SC-001)

```bash
python eval/gate.py --only intent_routing --runs 5 \
    --baseline eval/baseline_intent_legacy.json
```

Expected: ≥ 95% and no worse than Jev's result on the same 88 cases (100%,
PR #27; there is no committed Jev baseline file, only the legacy router's
77.3%). The measured GLiDE result is committed as
`eval/baseline_intent_glide.json`. Needs Gemini for the
second-opinion path; if the Gemini spend cap is active (issue #59) the gate
cannot run and the move waits.

## 4. Thresholds (FR-003)

```bash
uv run python eval/probe_glide.py --scores eval/cases/intent_routing.jsonl
```

Expected: a table of certainty and `reports_food` per case. Choose
`intent_min_probability` and `log_offer_min_probability` from it, record the
distribution in research.md R4, re-run step 3.

## 5. Latency (SC-002)

```bash
uv run python eval/probe_glide.py --n 50 --concurrency 1,5,10
railway ssh --service web -- python eval/probe_glide.py --n 50
```

Go: container p50 < 300 ms and p95 < 800 ms at concurrency 1. No-go: p50 >
500 ms. Run it once after 15 idle minutes too, to see whether the model goes
cold.

## 6. Unavailable service (SC-003)

With `FASTINO_API_KEY` unset, then with `glide.base_url` pointed at an
unroutable address: send "greek yogurt" and "is oatmeal healthy?" through the
local backend on a throwaway database. Both get the right kind of reply; the
Logfire span shows `path = second_opinion_unavailable` and the wait stays under
`request_timeout_s`.

## 7. After shipping

Ship with `/ship` after adding `FASTINO_API_KEY` to the Railway `web` and
`bot` services. In Logfire over the first day: share of turns with
`path = judgment` ≥ 90% (SC-004), `judge_model = glide`, routing p95, and
`judgment_input_tokens` per turn. Then remove `TYPESAFE_API_KEY` from Railway.
