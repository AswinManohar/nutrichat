# Pricing UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Plan & Usage" card to SettingsPage and a `/upgrade` page so users can see their LLM quota and upgrade to the paid tier with one click (mock — no Stripe).

**Architecture:** Three tasks in dependency order: data layer (types + hooks) first, then the Settings card that consumes them, then the standalone `/upgrade` page and its route. No new shared components — all UI uses existing `Card`, `Button`, and `CardHeader`/`CardContent` primitives from `frontend/src/components/ui/`.

**Tech Stack:** React 19, TypeScript, TanStack Query v5, react-router-dom v7, Tailwind CSS, lucide-react. No new dependencies.

## Global Constraints

- All file paths in this plan are relative to the repo root.
- Frontend source lives under `frontend/src/`.
- `tsc -b` (run from `frontend/`) is the type-check command; it must pass after every task.
- No new npm packages. Use existing: `@tanstack/react-query`, `react-router-dom`, `lucide-react`.
- Copy rule: use "AI requests" not "messages" everywhere (one message can cost 1–2 AI requests).
- Price display: em-dash `—` (not a hyphen) followed by `/ mo`.
- `tier` must always be typed as `'free' | 'paid'` — never `string`.
- Follow the existing hook pattern in `frontend/src/api/hooks.ts`: named exports, `useQuery`/`useMutation` from `@tanstack/react-query`, `apiClient` from `./client`.
- Tailwind classes must match the existing design system: `bg-surface`, `bg-sand`, `bg-container`, `text-ink`, `text-muted`, `text-sage-deep`, `border-sand-border`, `bg-sage`, `bg-danger`, `bg-warn`, `rounded-2xl`, `font-display`.

---

### Task 1: Data Layer — Types and Hooks

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/hooks.ts`

**Interfaces:**
- Produces: `QuotaStatus`, `UpgradeResponse` (types); `useQuota()`, `useUpgradeQuota()` (hooks) — consumed by Tasks 2 and 3.

- [ ] **Step 1: Add types to `frontend/src/api/types.ts`**

  Append at the end of the file:

  ```ts
  export interface QuotaStatus {
    used: number
    limit: number
    remaining: number
    exhausted: boolean
    tier: 'free' | 'paid'
  }

  export interface UpgradeResponse {
    upgraded: boolean
    new_quota: number
  }
  ```

- [ ] **Step 2: Add `QuotaStatus` and `UpgradeResponse` to the import block in `frontend/src/api/hooks.ts`**

  The file already imports named types from `./types`. Add the two new ones:

  ```ts
  import type {
    // ... existing imports ...
    QuotaStatus,
    UpgradeResponse,
  } from './types'
  ```

- [ ] **Step 3: Add `useQuota` hook to `frontend/src/api/hooks.ts`**

  Append after the last export in the file:

  ```ts
  export const useQuota = () => {
    return useQuery<QuotaStatus, ApiError>({
      queryKey: ['quota'],
      queryFn: () => apiClient.get<QuotaStatus>('/quota'),
      staleTime: 30_000,
      retry: (failureCount, error) => {
        if (error.status === 404) return false
        return failureCount < 3
      },
    })
  }
  ```

  > `retry: false` on 404 — a 404 from `/quota` means the user has no `user_goal` row (not onboarded). This is a genuine error state inside ProtectedLayout, not a transient miss. Matches the pattern used by `useGoals` and `useNutrientCheckup`.

- [ ] **Step 4: Add `useUpgradeQuota` hook to `frontend/src/api/hooks.ts`**

  Append directly after `useQuota`:

  ```ts
  export const useUpgradeQuota = () => {
    const queryClient = useQueryClient()
    return useMutation<UpgradeResponse, ApiError, void>({
      mutationFn: () => apiClient.post<UpgradeResponse>('/billing/upgrade'),
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: ['quota'] })
      },
    })
  }
  ```

  > `onSuccess` invalidates `['quota']` so the Settings card and the UpgradePage both reflect the new tier without a page reload.

- [ ] **Step 5: Type-check**

  ```bash
  cd frontend && npx tsc -b --noEmit
  ```

  Expected: zero errors.

- [ ] **Step 6: Commit**

  ```bash
  git add frontend/src/api/types.ts frontend/src/api/hooks.ts
  git commit -m "feat(quota-ui): add QuotaStatus, UpgradeResponse types + useQuota, useUpgradeQuota hooks"
  ```

---

### Task 2: Settings Card — "Plan & Usage"

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

**Interfaces:**
- Consumes: `useQuota()` from Task 1 — returns `QuotaStatus | undefined`.

- [ ] **Step 1: Add missing imports to `SettingsPage.tsx`**

  The file already imports from `react-router-dom` — check if `useNavigate` is present. It is not. Add it.

  Find the line:
  ```ts
  import React, { useState } from 'react'
  ```
  Replace with:
  ```ts
  import React, { useState } from 'react'
  import { useNavigate } from 'react-router-dom'
  ```

  Find the hook imports block (starts with `useGoals`). Add `useQuota`:
  ```ts
  import {
    useGoals,
    useUpdateGoals,
    useTelegramLinkStatus,
    useGenerateTelegramLinkCode,
    useDisconnectTelegram,
    useQuota,
  } from '../api/hooks'
  ```

  Find the lucide-react import line:
  ```ts
  import { Sparkles, Save, ShieldAlert, LogOut, Heart, Target, Send } from 'lucide-react'
  ```
  Add `Zap`:
  ```ts
  import { Sparkles, Save, ShieldAlert, LogOut, Heart, Target, Send, Zap } from 'lucide-react'
  ```

- [ ] **Step 2: Call hooks inside the component**

  In `SettingsPage`, after the existing hook calls (after `const { enabled: mascotEnabled … }` line), add:

  ```ts
  const navigate = useNavigate()
  const { data: quota } = useQuota()
  const quotaPct = quota ? Math.min(100, Math.round((quota.used / quota.limit) * 100)) : 0
  ```

- [ ] **Step 3: Insert the Plan & Usage card**

  In the JSX, find the closing `</Card>` tag of the Telegram Bot card and the opening `<Card` of the Appearance card. Insert the new card between them:

  ```tsx
  {/* Plan & Usage Card */}
  {quota && (
    <Card className="border border-sand-border bg-sand backdrop-blur-md">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Zap className="w-4 h-4 text-sage-deep" />
          Plan & Usage
        </CardTitle>
        <CardDescription>
          {quota.tier === 'paid' ? 'Pro plan' : 'Free plan'}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between text-xs text-muted">
          <span>{quota.used} / {quota.limit} AI requests</span>
          <span>{quotaPct}% used</span>
        </div>
        <div className="w-full h-2 bg-container rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-300 ${
              quota.exhausted
                ? 'bg-danger'
                : quotaPct >= 80
                ? 'bg-warn'
                : 'bg-sage'
            }`}
            style={{ width: `${quotaPct}%` }}
          />
        </div>
        {quota.tier === 'paid' ? (
          <p className="text-xs text-sage-deep font-medium">
            You're on the Pro plan
          </p>
        ) : (
          <Button
            type="button"
            variant="primary"
            size="sm"
            onClick={() => navigate('/upgrade')}
            className="w-full mt-1"
          >
            {quota.exhausted ? 'Upgrade to unlock more' : 'Upgrade →'}
          </Button>
        )}
      </CardContent>
    </Card>
  )}
  ```

  > The card is hidden (`quota` is `undefined`) while loading or on error, which satisfies the "return null on error/loading" spec requirement without extra state.

- [ ] **Step 4: Type-check**

  ```bash
  cd frontend && npx tsc -b --noEmit
  ```

  Expected: zero errors.

- [ ] **Step 5: Visual check**

  Start the dev server with a live backend (or in bypass mode via `X-Debug-User-Id` header):

  ```bash
  cd frontend && npm run dev
  ```

  Navigate to Settings. Confirm:
  - "Plan & Usage" card appears between Telegram and Appearance cards.
  - Progress bar fills proportionally.
  - Bar is green under 80%, amber at ≥ 80%, red when exhausted.
  - "Upgrade →" button navigates to `/upgrade` (which 404s until Task 3).
  - When `tier === 'paid'`, button is replaced by "You're on the Pro plan" text.
  - Card is absent when `useQuota()` returns an error or while loading.

- [ ] **Step 6: Commit**

  ```bash
  git add frontend/src/pages/SettingsPage.tsx
  git commit -m "feat(quota-ui): Plan & Usage card in Settings with progress bar and upgrade CTA"
  ```

---

### Task 3: `/upgrade` Page and Route

**Files:**
- Create: `frontend/src/pages/UpgradePage.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `useQuota()`, `useUpgradeQuota()` from Task 1.

- [ ] **Step 1: Create `frontend/src/pages/UpgradePage.tsx`**

  ```tsx
  import React, { useEffect, useState } from 'react'
  import { useNavigate } from 'react-router-dom'
  import { ArrowLeft, Star, Check } from 'lucide-react'
  import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card'
  import { Button } from '../components/ui/button'
  import { useQuota, useUpgradeQuota } from '../api/hooks'

  const FREE_FEATURES = ['Meal logging', 'AI coaching', 'Meal history']
  const PRO_FEATURES = ['Everything free', '3× more requests', 'Priority access']

  export const UpgradePage: React.FC = () => {
    const navigate = useNavigate()
    const { data: quota } = useQuota()
    const upgradeMutation = useUpgradeQuota()
    const [successMsg, setSuccessMsg] = useState<string | null>(null)
    const [errorMsg, setErrorMsg] = useState<string | null>(null)

    const isPaid = quota?.tier === 'paid'

    useEffect(() => {
      if (!successMsg) return
      const id = setTimeout(() => navigate('/settings'), 1500)
      return () => clearTimeout(id)
    }, [successMsg, navigate])

    const handleUpgrade = () => {
      setErrorMsg(null)
      upgradeMutation.mutate(undefined, {
        onSuccess: () => setSuccessMsg("You're now on Pro!"),
        onError: () => setErrorMsg('Something went wrong. Try again.'),
      })
    }

    return (
      <div className="flex-1 overflow-y-auto bg-surface p-4 md:p-8">
        <div className="max-w-2xl mx-auto space-y-6">
          {/* Header */}
          <div className="flex items-center gap-3 border-b border-sand-border pb-5">
            <button
              type="button"
              onClick={() => navigate('/settings')}
              className="text-muted hover:text-ink transition-colors flex items-center gap-1.5 text-sm"
            >
              <ArrowLeft className="w-4 h-4" />
              Back to Settings
            </button>
          </div>

          <div>
            <h1 className="font-display font-bold text-xl text-ink">Choose your plan</h1>
            <p className="text-xs text-muted mt-1">Lifetime AI requests — never reset</p>
          </div>

          {/* Status banners */}
          {isPaid && !successMsg && (
            <div className="bg-container border border-sage/30 text-sage-deep text-xs p-3 rounded-xl">
              You're already on the Pro plan.
            </div>
          )}
          {successMsg && (
            <div className="bg-container border border-sage/30 text-sage-deep text-xs p-3 rounded-xl flex items-center gap-2">
              <Star className="w-4 h-4" />
              {successMsg}
            </div>
          )}
          {errorMsg && (
            <div className="bg-danger/10 border border-danger/30 text-danger text-xs p-3 rounded-xl">
              {errorMsg}
            </div>
          )}

          {/* Tier cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Free tier */}
            <Card className="border border-sand-border bg-sand backdrop-blur-md">
              <CardHeader>
                <CardTitle>Free</CardTitle>
                <CardDescription>50 AI requests · lifetime</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <ul className="space-y-2">
                  {FREE_FEATURES.map((f) => (
                    <li key={f} className="flex items-center gap-2 text-sm text-ink-soft">
                      <Check className="w-3.5 h-3.5 text-sage-deep shrink-0" />
                      {f}
                    </li>
                  ))}
                </ul>
                <div>
                  <p className="text-2xl font-display font-bold text-ink">
                    — <span className="text-sm font-normal text-muted">/ mo</span>
                  </p>
                  <p className="text-xs text-muted mt-0.5">Pricing coming soon</p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  className="w-full"
                  disabled
                >
                  {isPaid ? 'Free' : 'Current plan'}
                </Button>
              </CardContent>
            </Card>

            {/* Pro tier */}
            <Card className="border border-sage/40 bg-sand backdrop-blur-md">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>Pro</CardTitle>
                  <span className="flex items-center gap-1 text-xs text-sage-deep font-medium bg-sage/10 px-2 py-0.5 rounded-full">
                    <Star className="w-3 h-3" />
                    {isPaid ? 'Current plan' : 'Best'}
                  </span>
                </div>
                <CardDescription>150 AI requests · lifetime</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <ul className="space-y-2">
                  {PRO_FEATURES.map((f) => (
                    <li key={f} className="flex items-center gap-2 text-sm text-ink-soft">
                      <Check className="w-3.5 h-3.5 text-sage-deep shrink-0" />
                      {f}
                    </li>
                  ))}
                </ul>
                <div>
                  <p className="text-2xl font-display font-bold text-ink">
                    — <span className="text-sm font-normal text-muted">/ mo</span>
                  </p>
                  <p className="text-xs text-muted mt-0.5">Pricing coming soon</p>
                </div>
                <Button
                  type="button"
                  variant="primary"
                  className="w-full"
                  disabled={isPaid || upgradeMutation.isPending}
                  isLoading={upgradeMutation.isPending}
                  onClick={isPaid ? undefined : handleUpgrade}
                >
                  {isPaid ? 'Current plan' : 'Upgrade now'}
                </Button>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    )
  }
  ```

- [ ] **Step 2: Register the route in `frontend/src/App.tsx`**

  Add the import at the top of the file alongside the other page imports:

  ```ts
  import { UpgradePage } from './pages/UpgradePage'
  ```

  Inside the `<Route element={<ProtectedLayout />}>` block, add:

  ```tsx
  <Route path="/upgrade" element={<UpgradePage />} />
  ```

  Place it after the `/settings` route. The full block will look like:

  ```tsx
  <Route element={<ProtectedLayout />}>
    <Route path="/onboarding" element={<OnboardingPage />} />
    <Route path="/chat" element={<ChatPage />} />
    <Route path="/my-meals" element={<MyMealsPage />} />
    <Route path="/trends" element={<TrendsPage />} />
    <Route path="/settings" element={<SettingsPage />} />
    <Route path="/upgrade" element={<UpgradePage />} />
    <Route path="/" element={<Navigate to="/chat" replace />} />
  </Route>
  ```

- [ ] **Step 3: Type-check**

  ```bash
  cd frontend && npx tsc -b --noEmit
  ```

  Expected: zero errors.

- [ ] **Step 4: Visual check**

  ```bash
  cd frontend && npm run dev
  ```

  Navigate to `/upgrade`. Confirm all states:

  **Free user (default):**
  - Free card shows "Current plan" (disabled button, muted).
  - Pro card shows "Upgrade now" (active, sage-green).
  - Both price lines show "— / mo" with "Pricing coming soon" below.

  **Click "Upgrade now":**
  - Button shows spinner while mutation is pending.
  - On success: green banner "You're now on Pro!" appears, page navigates to `/settings` after 1.5 s.
  - After navigating back to `/settings`, the Plan & Usage card shows "Pro plan" and "You're on the Pro plan" (no Upgrade button).

  **Revisit `/upgrade` after upgrade:**
  - Banner "You're already on the Pro plan." shown.
  - Pro card badge says "Current plan".
  - Both buttons disabled.

  **Back link:**
  - "← Back to Settings" navigates to `/settings`.

  **Error simulation** (temporarily point API to a bad URL or mock):
  - Error banner "Something went wrong. Try again." appears below the banners section.
  - Upgrade button re-enables.

- [ ] **Step 5: Commit**

  ```bash
  git add frontend/src/pages/UpgradePage.tsx frontend/src/App.tsx
  git commit -m "feat(quota-ui): /upgrade page with Free/Pro tier cards and instant mock upgrade"
  ```
