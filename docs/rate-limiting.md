# Rate limiting

How Mealsy throttles request rate, and what is wired up today. Implementation:
`src/backend/ratelimit.py`; wiring in `src/backend/main.py` and
`src/backend/api/meals.py`.

Rate limiting is distinct from the **credit quota** (`backend/quota.py`,
`FREE_QUOTA=50` / `PAID_QUOTA=150`): the quota caps *lifetime LLM spend* per
user; rate limiting caps *how fast* requests can arrive. They stack — a request
can pass the rate limiter and still be refused by the quota, or vice versa.

## The two layers

| Layer | Where | Scope key | Default limit | Applies to |
|---|---|---|---|---|
| Per-IP middleware | `RateLimitMiddleware` (main.py) | `ip` = client IP | **120 / 60s** (`RATE_LIMIT_IP_PER_MIN`) | every non-exempt route |
| Per-user dependency | `user_rate_limiter(...)` (meals.py) | `chat` = user ID | **20 / 60s** (`CHAT_RATE_LIMIT`) | `POST /meals/log` only |

Both go through the same counter (`check_rate_limit`), so behavior — fixed
window, fail-open, Retry-After — is identical; only the identity and bucket
differ.

### Per-IP middleware (coarse flood protection)

Added in `main.py` and runs on **every** request except exempt paths:

```python
app.add_middleware(
    RateLimitMiddleware,
    limit=int(os.environ.get("RATE_LIMIT_IP_PER_MIN", "120")),
    window_s=60,
)
```

- **Exempt paths:** only `/health` (`EXEMPT_PATHS`). Everything else — including
  `/docs`, `/openapi.json`, and all API routes — is subject to the 120/min IP
  limit.
- **Client IP resolution** (`client_ip`): uses the **last** hop of
  `X-Forwarded-For`. Railway's edge proxy appends the real client IP there;
  earlier XFF entries are attacker-controllable and ignored. Falls back to the
  socket peer, then `"unknown"`. This is what keeps every user from sharing one
  IP bucket behind the proxy.
- **Middleware order:** `RateLimitMiddleware` is added *before* `CORSMiddleware`.
  Starlette runs the last-added middleware outermost, so CORS wraps the limiter
  and a `429` still carries the correct CORS headers (a browser can read it).

### Per-user dependency (fine-grained, per endpoint)

`user_rate_limiter(scope, limit, window_s)` builds a FastAPI dependency keyed by
the authenticated `user_id`. Currently attached to exactly one endpoint:

```python
@router.post(
    "/log",
    dependencies=[Depends(user_rate_limiter("chat", limit=CHAT_RATE_LIMIT, window_s=60))],
)
```

So a single user can hit the LLM chat/log path at most **20 times per minute**,
regardless of the shared per-IP budget. No other endpoint has a per-user limit
yet — adding one is a one-line `dependencies=[...]` with a fresh `scope`.

## How the counter works

`check_rate_limit(identity, scope, limit, window_s)` is a **fixed-window** Redis
counter, key `ratelimit:{scope}:{identity}`:

1. `INCR` the key. On the first hit of a window (`count == 1`) set `EXPIRE
   window_s`.
2. Read `TTL`. If it's negative — the key exists without an expiry, e.g. a crash
   between `INCR` and `EXPIRE` — re-arm `EXPIRE` so an identity is never blocked
   forever.
3. If `count > limit` → **blocked**: `allowed=False`, `retry_after_s = max(ttl,
   1)`. Otherwise → **allowed**, `remaining = limit - count`.

**Fixed-window caveat:** counts reset at the window boundary, not on a sliding
basis. A client can send up to `limit` at the end of one window and `limit`
again at the start of the next, i.e. briefly ~2× the nominal rate across a
boundary. This is an accepted trade for a simple, cheap counter.

**Fail-open:** any Redis exception is caught, logged as `ratelimit_redis_error`,
and the request is **allowed**. A Redis outage degrades to "no throttling"
rather than taking the whole API down.

## The 429 response

Both layers return the same shape when a limit is exceeded:

```
HTTP 429 Too Many Requests
Retry-After: <seconds until the window resets>
{"detail": "Rate limit exceeded. Try again shortly."}
```

The middleware returns a `JSONResponse` directly; the per-user dependency raises
`HTTPException(429, ...)`. The `Retry-After` header is the remaining window TTL
(minimum 1s).

## Configuration

| Knob | Where | Default | Effect |
|---|---|---|---|
| `RATE_LIMIT_IP_PER_MIN` | env (Railway) | `120` | per-IP requests per 60s |
| `CHAT_RATE_LIMIT` | constant in `api/meals.py` | `20` | per-user `/meals/log` per 60s |
| window | hard-coded | `60s` | window length for both layers |
| `EXEMPT_PATHS` | constant in `ratelimit.py` | `{"/health"}` | paths the IP middleware skips |

Only `RATE_LIMIT_IP_PER_MIN` is env-tunable without a code change; the per-user
limit, windows, and exempt set are in code.

## Observability

Logfire events:

- `ratelimit_ip_blocked` — `{path}` — IP layer rejected a request.
- `ratelimit_user_blocked` — `{scope, user_id}` — per-user layer rejected.
- `ratelimit_redis_error` — `{scope, error}` — Redis failed; request allowed.

## Currently implemented — summary

- ✅ Per-IP middleware on all routes except `/health`, 120/min (env-tunable).
- ✅ Per-user limit on `POST /meals/log`, 20/min.
- ✅ Redis fixed-window counter, fails open, TTL self-heal.
- ✅ Correct client-IP behind Railway's proxy (last XFF hop).
- ✅ `429` + `Retry-After`, CORS-wrapped.
- ✅ Tests: `tests/test_rate_limit.py`.

Not done yet (possible follow-ups): per-user limits on other LLM endpoints
(coaching, decompose), sliding-window or token-bucket if edge bursts matter,
surfacing `X-RateLimit-*` headers on successful responses, and per-plan
(free vs paid) limits.
