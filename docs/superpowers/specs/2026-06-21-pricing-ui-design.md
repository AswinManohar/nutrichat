# Pricing UI Design

**Date:** 2026-06-21  
**Status:** Approved  
**Author:** AswinManohar  
**Related spec:** `2026-06-19-llm-rate-limiting-design.md`

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

### New type — `src/frontend/src/api/types.ts`

```ts
interface QuotaStatus {
  used: number
  limit: number
  remaining: number
  exhausted: boolean
  tier: 'free' | 'paid'   // literal union — never bare string
}
```

### New hooks — `src/frontend/src/api/hooks.ts`

```ts
// Reads current quota. staleTime: 30s — acceptable for a settings card.
export function useQuota(): UseQueryResult<QuotaStatus>

// Calls POST /billing/upgrade. On success: invalidates ['quota'] query key
// so both the Settings card and any other consumer refresh automatically.
export function useUpgradeQuota(): UseMutationResult<UpgradeResponse>
```

Query key: `['quota']`.

---

## Settings Card ("Plan & Usage")

**File:** `src/frontend/src/pages/SettingsPage.tsx` (modify)

Positioned between the Telegram card and the Appearance card. Rendered from
`useQuota()` data.

### Visual states

| State | Bar colour | Button |
|---|---|---|
| Free, under 80% | Sage green | "Upgrade →" (navigates to `/upgrade`) |
| Free, ≥ 80% used | Amber | "Upgrade →" |
| Free, exhausted | Red | "Upgrade to unlock more" |
| Paid | Sage green | Hidden — replaced by "You're on the Pro plan" badge |

Progress bar fill: `(used / limit) * 100%`, capped at 100%.

### Loading state

Skeleton bar and muted placeholder text while `useQuota()` is in the loading
state. No error UI needed here — if the fetch fails, the card simply stays in
skeleton state (the user can still use the rest of Settings).

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

**File:** `src/frontend/src/pages/UpgradePage.tsx` (new)  
**Route:** `/upgrade` inside `ProtectedLayout` in `App.tsx`

### Layout

Two cards side by side (stacks to single column on mobile via Tailwind
`grid-cols-1 md:grid-cols-2`). Uses the existing `Card` component from
`src/frontend/src/components/ui/card.tsx`.

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

### Tier card states

- **User is on free:** Free card shows "Current plan" (disabled, muted button).
  Pro card shows "Upgrade now" (active CTA).
- **User is on paid:** Both buttons disabled. Banner above the cards: "You're
  already on the Pro plan." Pro card has a ★ "Current plan" badge instead.
- **Mutation loading:** "Upgrade now" button shows spinner, disabled.
- **Mutation error:** Toast ("Something went wrong. Try again.") — use existing
  toast pattern if present, otherwise `console.error`.
- **Mutation success:** Brief success banner ("You're now on Pro!"), then
  navigate to `/settings` after 1.5 s.

### Price display

Both cards show `— / mo` with a `text-muted` note "Pricing coming soon" below.
No placeholder dollar amount — avoids anchoring users to a number that will
change when Stripe lands.

### Navigation

- Back arrow / "← Back to Settings" link at the top navigates to `/settings`.
- After successful upgrade: `useNavigate()` to `/settings` after 1.5 s delay.

---

## Component Breakdown

| Component / file | Responsibility |
|---|---|
| `src/api/types.ts` | Add `QuotaStatus` interface |
| `src/api/hooks.ts` | Add `useQuota()`, `useUpgradeQuota()` |
| `src/pages/SettingsPage.tsx` | Add "Plan & Usage" card |
| `src/pages/UpgradePage.tsx` | New page — tier comparison + upgrade CTA |
| `src/App.tsx` | Add `/upgrade` route inside `ProtectedLayout` |

No new shared components needed — the page uses the existing `Card`, `Button`,
and `CardHeader`/`CardContent` primitives.

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| `useQuota()` fetch fails | Settings card stays in skeleton state silently |
| `useUpgradeQuota()` mutation fails | Toast error, button re-enables |
| `POST /billing/upgrade` returns 404 (not onboarded) | Should not occur in practice (user is in the protected app); treat as generic error |

---

## Stripe Integration Path

When Stripe is ready, the only change needed is in `UpgradePage.tsx`: replace
the `useUpgradeQuota()` mutation call with a redirect to Stripe's hosted
checkout URL. The backend `/billing/upgrade` endpoint becomes a Stripe webhook
handler instead of a direct mutation. The rest of the UI (card layout, quota
display, settings card) is unchanged.

---

## Files Touched

| File | Change |
|---|---|
| `src/frontend/src/api/types.ts` | Add `QuotaStatus` interface |
| `src/frontend/src/api/hooks.ts` | Add `useQuota`, `useUpgradeQuota` |
| `src/frontend/src/pages/SettingsPage.tsx` | Add "Plan & Usage" card |
| `src/frontend/src/pages/UpgradePage.tsx` | New file |
| `src/frontend/src/App.tsx` | Add `/upgrade` route |
