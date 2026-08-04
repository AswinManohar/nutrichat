# Pricing UI Design

**Date:** 2026-06-21  
**Revised:** 2026-06-21 (post spec review)  
**Status:** Approved  
**Author:** AswinManohar  
**Related spec:** `2026-06-19-llm-rate-limiting-design.md`

> All file paths below are relative to the repo root. Frontend files live under
> `frontend/src/`.

---

## Problem

The backend LLM quota system is implemented and working, but there is no frontend
surface for users to see their usage or upgrade to the paid tier. Users who hit
the quota wall get a text message telling them to visit `nutrichat.app/upgrade`,
which does not yet exist.

---

## What We're Building

Two surfaces:

1. **"Plan & Usage" card in SettingsPage** — compact quota indicator with an
   Upgrade button that links to the upgrade page.
2. **`/upgrade` page** — a dedicated pricing comparison page (Free vs Pro) where
   the user can upgrade with one click (mock — no Stripe yet).

---

## Backend Contracts (already implemented)

```
GET  /quota           → { used, limit, remaining, exhausted, tier }
POST /billing/upgrade → { upgraded: true, new_quota: 150 }
                        → 404 if user has no user_goal row (not onboarded)
```

Quota constants: `FREE_QUOTA = 50`, `PAID_QUOTA = 150`.

See `docs/superpowers/specs/2026-06-19-llm-rate-limiting-design.md` for full
backend design including atomic counter, degrade behaviour, and security
properties.

---

## Data Layer

### New types — `frontend/src/api/types.ts`

```ts
interface QuotaStatus {
  used: number
  limit: number
  remaining: number
  exhausted: boolean
  tier: 'free' | 'paid'   // literal union — never bare string
}

interface UpgradeResponse {
  upgraded: boolean
  new_quota: number
}
```

### New hooks — `frontend/src/api/hooks.ts`

```ts
// Reads current quota.
// staleTime: 30 000 ms — acceptable for a settings card.
// retry: false on 404 — the user is always onboarded inside ProtectedLayout,
// so a 404 is a genuine error, not a transient miss. Matches the retry pattern
// used by useGoals / useNutrientCheckup in this codebase.
export function useQuota(): UseQueryResult<QuotaStatus>

// Calls POST /billing/upgrade.
// onSuccess: invalidates ['quota'] query key so Settings card and any other
// consumer refresh automatically without a page reload.
export function useUpgradeQuota(): UseMutationResult<UpgradeResponse>
```

Query key: `['quota']`.

---

## Settings Card ("Plan & Usage")

**File:** `frontend/src/pages/SettingsPage.tsx` (modify)

Positioned between the Telegram card and the Appearance card. This is a soft
pointer — if new cards are added later, re-check placement.

`SettingsPage` already has a full-page loading gate on `goalsLoading`. The quota
card only renders after that resolves, so the card's own loading state only
matters when `useQuota()` is slower than `useGoals()`. Keep the card hidden
(`return null`) while `quotaLoading` is true; this avoids a skeleton that users
would rarely see.

### Visual states

| State | Bar colour | Button |
|---|---|---|
| Free, under 80% | Sage green | "Upgrade →" (navigates to `/upgrade`) |
| Free, ≥ 80% used | Amber | "Upgrade →" |
| Free, exhausted | Red | "Upgrade to unlock more" |
| Paid | Sage green | Hidden — replaced by "You're on the Pro plan" badge |

Progress bar fill: `(used / limit) * 100%`, capped at 100%.

### Error state

If `useQuota()` errors (network failure, 5xx), hide the card entirely — return
`null`. Do not show a persistent skeleton. The user can still use the rest of
Settings; the card reappears on next successful fetch.

### Copy

```
Plan & Usage
────────────
Free plan            ← "Pro plan" when tier === 'paid'
████████░░  34 / 50 AI requests
```

Use "AI requests" not "messages" — a single message can cost 1–2 AI requests
on ambiguous input (see related spec).

---

## `/upgrade` Page

**File:** `frontend/src/pages/UpgradePage.tsx` (new)  
**Route:** `/upgrade` inside `ProtectedLayout` in `frontend/src/App.tsx`

### Layout

Two cards side by side (stacks to single column on mobile via Tailwind
`grid-cols-1 md:grid-cols-2`). Uses the existing `Card` component from
`frontend/src/components/ui/card.tsx`.

```
┌─────────────────────┐  ┌─────────────────────┐
│  Free               │  │  Pro          ★ Best │
│  ─────────────────  │  │  ─────────────────── │
│  50 AI requests     │  │  150 AI requests     │
│  lifetime           │  │  lifetime            │
│                     │  │                      │
│  ✓ Meal logging     │  │  ✓ Everything free   │
│  ✓ AI coaching      │  │  ✓ 3× more requests  │
│  ✓ Meal history     │  │  ✓ Priority access   │
│                     │  │                      │
│  — / mo             │  │  — / mo              │
│  Pricing coming soon│  │  Pricing coming soon │
│                     │  │                      │
│  [Current plan]     │  │  [ Upgrade now ]     │
└─────────────────────┘  └─────────────────────┘
```

Price display: em-dash `—` (not a hyphen) followed by `/ mo`, with a
`text-muted` note "Pricing coming soon" below.

### Tier card states

- **User is on free:** Free card shows "Current plan" (disabled, muted button).
  Pro card shows "Upgrade now" (active CTA).
- **User is on paid:** Both buttons disabled. Banner above the cards: "You're
  already on the Pro plan." Pro card shows a ★ "Current plan" badge instead.
- **Mutation loading:** "Upgrade now" button shows spinner, disabled.
- **Mutation error:** Inline error banner below the Pro card (same pattern as the
  save-success banner in `SettingsPage` — local state, no toast library needed).
  Text: "Something went wrong. Try again." Button re-enables.
- **Mutation success:** Inline success banner ("You're now on Pro!"). Navigate
  to `/settings` after 1 500 ms. Use a `useEffect` with a cleanup to clear the
  timeout if the component unmounts before it fires — avoids a state update on
  an unmounted component.

### Navigation

- "← Back to Settings" link at the top using `useNavigate()`.
- After successful upgrade: navigate to `/settings` via a `useEffect`-managed
  timeout (see above).

---

## Component Breakdown

All paths are relative to the repo root.

| File | Change |
|---|---|
| `frontend/src/api/types.ts` | Add `QuotaStatus`, `UpgradeResponse` |
| `frontend/src/api/hooks.ts` | Add `useQuota`, `useUpgradeQuota` |
| `frontend/src/pages/SettingsPage.tsx` | Add "Plan & Usage" card |
| `frontend/src/pages/UpgradePage.tsx` | New file |
| `frontend/src/App.tsx` | Add `/upgrade` route inside `ProtectedLayout` |

No new shared components needed — the page uses the existing `Card`, `Button`,
and `CardHeader`/`CardContent` primitives.

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| `useQuota()` fetch fails | Hide card (`return null`) — user can still use Settings |
| `useQuota()` returns 404 | `retry: false` — card hides (shouldn't happen inside ProtectedLayout) |
| `useUpgradeQuota()` mutation fails | Inline error banner on UpgradePage, button re-enables |
| `POST /billing/upgrade` 404 | Treated as generic mutation error — banner shown |

---

## Stripe Integration Path

When Stripe is ready, one change in `frontend/src/pages/UpgradePage.tsx`:
replace the `useUpgradeQuota()` mutation call with a redirect to Stripe's hosted
checkout URL. The backend `/billing/upgrade` endpoint becomes a Stripe webhook
handler. Everything else — the card layout, quota display, settings card,
`useQuota` hook — is unchanged.

---

## Files Touched

All paths are relative to the repo root.

| File | Change |
|---|---|
| `frontend/src/api/types.ts` | Add `QuotaStatus`, `UpgradeResponse` interfaces |
| `frontend/src/api/hooks.ts` | Add `useQuota`, `useUpgradeQuota` hooks |
| `frontend/src/pages/SettingsPage.tsx` | Add "Plan & Usage" card |
| `frontend/src/pages/UpgradePage.tsx` | New file |
| `frontend/src/App.tsx` | Add `/upgrade` route |
