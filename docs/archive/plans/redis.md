# Plan: Redis Client Layer

> Source PRD: nutrichat-prd-final.md

## Architectural decisions

Durable decisions that apply across all phases:

- **Data Models**: Use `TodayTotals` (custom Python Pydantic or Dataclass) to structure and validate returned session memory securely.
- **Cache Lifecycle**: TTL for all daily session keys must be exactly 24h to avoid caching stale limits or bloating server RAM.
- **Backend Strategy**: Redis is exclusively used for rapid session caching. Long term persistence and history must hit Postgres.
- **Pipeline Processing**: Always use Redis pipelines (`HINCRBYFLOAT`) for atomicity guaranteeing macro totals are not corrupted by simultaneous updates.

---

## Phase 1: Connection Pool & Core Retrieval

**User stories**: The agent context orchestrator needs rapid latency-free access to the user's active session totals to build an accurate user prompt containing daily limitations without querying the heavy database index.

### What to build

A robust asynchronous connection pool utilizing `redis.asyncio` along with a fetcher abstraction loop (`get_today_totals`). This fetches active keys mapping them into the memory object without failing natively on empty or non-initialized hashes.

### Acceptance criteria

- [ ] Implements an asyncio compatible redis client connection.
- [ ] Returns a data container/model mapping kcal, protein, fiber, and meal counts properly.
- [ ] Defined default-fallback behaviors handle requests efficiently when a user's tracker hash hasn't been instantiated yet for that day.

---

## Phase 2: Atomic Write Pipeline

**User stories**: A meal logs successfully triggering the caching of new nutritional data values quickly. Users shouldn't double-log nor should they experience lag between verification and interface tracking updates.

### What to build

Implement `increment_today()` by pipelining `HINCRBYFLOAT` operations mapping to specific keys representing standard macro names. Ensure that it executes in batch, updating TTL timers immediately preventing the state mapping out of rhythm with standard daily time boundaries.

### Acceptance criteria

- [ ] Replaces distinct sequential I/O commands with atomic client transactions / pipelines.
- [ ] Dynamically updates standard macro counts incrementally instead of full hash replaces.

---

## Phase 3: Nightly Expiration

**User stories**: The Redis values shouldn't artificially spill into the following day causing the patient to inherit yesterday's nutritional consequences if they fail to log.

### What to build

Implement `reset_day_key()` to forcefully remove, expire, or reset tracking hashes mapped directly to individual users. Intended exclusively for external Celery cron behaviors or system overrides.

### Acceptance criteria

- [ ] Exposes a strict unlinking abstraction to forcefully drop the active daily hash instance tied to `user_id`.
