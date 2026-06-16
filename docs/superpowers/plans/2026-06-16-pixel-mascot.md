# Pixel Mascot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the existing typing-dot animations with an animated terracotta pixel creature on two surfaces (chat loading, startup loading), plus a rare idle peek from the bottom of the screen, with a Settings toggle to disable it.

**Architecture:** A single `MascotSprite` SVG component (inline `<rect>` elements, no external files) covers all visual states (`walk`, `idle`, `peek`). CSS keyframes in `index.css` drive all animation. A tiny Zustand store (`mascotStore.ts`) persists the enabled flag to localStorage. Every surface falls back to the original 3-dot animation when disabled.

**Tech Stack:** React 19 · TypeScript · Tailwind CSS · Zustand · CSS keyframes · SVG

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `frontend/src/stores/mascotStore.ts` | Create | `enabled` flag, localStorage persistence |
| `frontend/src/index.css` | Modify | Walk, blink, peek keyframes + helper classes |
| `frontend/src/components/mascot/MascotSprite.tsx` | Create | SVG pixel art, 3 animation states |
| `frontend/src/components/mascot/MascotPeek.tsx` | Create | Idle peek timer, fixed-position overlay |
| `frontend/src/components/chat/ChatThread.tsx` | Modify | Replace `TypingIndicator` inline function |
| `frontend/src/components/layout/ProtectedLayout.tsx` | Modify | Replace dots in `LoadingScreen`, mount `MascotPeek` |
| `frontend/src/pages/SettingsPage.tsx` | Modify | Add "Appearance" card with toggle |

---

## Task 1: Mascot store

**Files:**
- Create: `frontend/src/stores/mascotStore.ts`

- [ ] **Step 1: Create the store file**

```typescript
// frontend/src/stores/mascotStore.ts
import { create } from 'zustand'

function loadEnabled(): boolean {
  try {
    return localStorage.getItem('nutrichat-mascot-enabled') !== 'false'
  } catch {
    return true
  }
}

interface MascotState {
  enabled: boolean
  setEnabled: (v: boolean) => void
}

export const useMascotStore = create<MascotState>((set) => ({
  enabled: loadEnabled(),
  setEnabled: (enabled) => {
    try {
      localStorage.setItem('nutrichat-mascot-enabled', String(enabled))
    } catch {}
    set({ enabled })
  },
}))
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors relating to `mascotStore.ts`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/stores/mascotStore.ts
git commit -m "feat: mascot store — enabled flag with localStorage persistence"
```

---

## Task 2: CSS animation keyframes

**Files:**
- Modify: `frontend/src/index.css` (append before closing brace / after `.typing-dot` block, around line 121)

- [ ] **Step 1: Add the keyframes and classes**

Open `frontend/src/index.css`. After the `.typing-dot { … }` block (currently ends around line 121), insert the following block:

```css
/* ── Pixel mascot animations ─────────────────────────────────────────── */

@keyframes mascot-leg-left {
  0%, 100% { transform: translateY(0px); }
  50%      { transform: translateY(-4px); }
}

@keyframes mascot-leg-right {
  0%, 100% { transform: translateY(-4px); }
  50%      { transform: translateY(0px); }
}

@keyframes mascot-bob {
  0%, 100% { transform: translateY(0px); }
  25%, 75% { transform: translateY(-1px); }
}

@keyframes mascot-blink {
  0%, 88%, 100% { transform: scaleY(0); }
  92%, 97%      { transform: scaleY(1); }
}

@keyframes mascot-peek {
  0%   { transform: translateY(100%); }
  15%  { transform: translateY(calc(100% - 40px)); }
  82%  { transform: translateY(calc(100% - 40px)); }
  100% { transform: translateY(100%); }
}

.mascot-walk-body {
  animation: mascot-bob 800ms linear infinite;
}
.mascot-walk-leg-l {
  animation: mascot-leg-left 800ms linear infinite;
}
.mascot-walk-leg-r {
  animation: mascot-leg-right 800ms linear infinite;
}
.mascot-idle-eyelid {
  transform-box: fill-box;
  transform-origin: top center;
  animation: mascot-blink 3s ease-in-out infinite;
}
.mascot-peek-wrapper {
  animation: mascot-peek 3.2s ease-in-out forwards;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/index.css
git commit -m "feat: mascot CSS keyframes (walk, blink, peek)"
```

---

## Task 3: MascotSprite component

**Files:**
- Create: `frontend/src/components/mascot/MascotSprite.tsx`

The character is a 10-column × 12-row pixel grid. Each logical pixel = 4 SVG units. SVG viewBox `0 0 40 48`. The rendered CSS width is `size * 4` pixels; height scales automatically.

Pixel layout (`B` = body #C47A4A, `S` = body-shadow #A55E32, `E` = eye #1A1A1A, `L` = leg #C47A4A):
```
Row  0: ..BBBBBB..   cols 2-7  → x=8  w=24
Row  1: .BBBBBBBB.   cols 1-8  → x=4  w=32
Row  2: .BBBBBBBB.   cols 1-8
Row  3: .B..BB..B.   col1(x=4,w=4) cols4-5(x=16,w=8) col8(x=32,w=4) + eyes
Row  4: .BBBBBBBB.   cols 1-8
Row  5: .BBBBBBBB.   cols 1-8
Row  6: .BBBBBBBB.   cols 1-8
Row  7: ..SSSSSS..   cols 2-7  → shadow row
Row  8: ..LL..LL..   legs
Row  9: ..LL..LL..
Row 10: ..LL..LL..
Row 11: ..LL..LL..
```

- [ ] **Step 1: Create `frontend/src/components/mascot/MascotSprite.tsx`**

```typescript
// frontend/src/components/mascot/MascotSprite.tsx
interface MascotSpriteProps {
  size?: number
  state?: 'walk' | 'idle' | 'peek'
  className?: string
}

export function MascotSprite({ size = 10, state = 'idle', className }: MascotSpriteProps) {
  const w = size * 4

  const isWalk = state === 'walk'
  const isIdle = state === 'idle' || state === 'peek'

  return (
    <svg
      viewBox="0 0 40 48"
      style={{ width: w, imageRendering: 'pixelated' }}
      xmlns="http://www.w3.org/2000/svg"
      shapeRendering="crispEdges"
      className={className}
      aria-hidden="true"
    >
      {/* Body */}
      <g className={isWalk ? 'mascot-walk-body' : undefined}>
        {/* Row 0: cols 2-7 */}
        <rect x="8" y="0" width="24" height="4" fill="#C47A4A" />
        {/* Rows 1-2: cols 1-8 */}
        <rect x="4" y="4" width="32" height="8" fill="#C47A4A" />
        {/* Row 3: col 1, cols 4-5, col 8 (eye gaps at 2-3 and 6-7) */}
        <rect x="4" y="12" width="4" height="4" fill="#C47A4A" />
        <rect x="16" y="12" width="8" height="4" fill="#C47A4A" />
        <rect x="32" y="12" width="4" height="4" fill="#C47A4A" />
        {/* Rows 4-6: cols 1-8 */}
        <rect x="4" y="16" width="32" height="12" fill="#C47A4A" />
        {/* Row 7: cols 2-7, shadow */}
        <rect x="8" y="28" width="24" height="4" fill="#A55E32" />
      </g>

      {/* Eyes */}
      <g>
        <rect x="8"  y="12" width="8" height="4" fill="#1A1A1A" />
        <rect x="24" y="12" width="8" height="4" fill="#1A1A1A" />
        {/* Eye shine (1 logical pixel each) */}
        <rect x="8"  y="12" width="2" height="2" fill="#FFFFFF" />
        <rect x="24" y="12" width="2" height="2" fill="#FFFFFF" />
      </g>

      {/* Eyelids (blink overlay, scaleY(0) by default, scales to 1 on blink) */}
      {isIdle && (
        <g>
          <rect x="8"  y="12" width="8" height="4" fill="#C47A4A" className="mascot-idle-eyelid" />
          <rect x="24" y="12" width="8" height="4" fill="#C47A4A" className="mascot-idle-eyelid" />
        </g>
      )}

      {/* Left leg */}
      <g className={isWalk ? 'mascot-walk-leg-l' : undefined}>
        <rect x="8" y="32" width="8" height="16" fill="#C47A4A" />
      </g>

      {/* Right leg */}
      <g className={isWalk ? 'mascot-walk-leg-r' : undefined}>
        <rect x="24" y="32" width="8" height="16" fill="#C47A4A" />
      </g>
    </svg>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors in `MascotSprite.tsx`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/mascot/MascotSprite.tsx
git commit -m "feat: MascotSprite — terracotta SVG pixel creature with walk/idle/peek states"
```

---

## Task 4: MascotPeek component

**Files:**
- Create: `frontend/src/components/mascot/MascotPeek.tsx`

Fires once per session: 60 s after mount if the user has been idle (no `pointermove`) for ≥ 30 s. The animation is 3.2 s total (slides up, holds, slides back). After it completes, the component unmounts itself.

- [ ] **Step 1: Create `frontend/src/components/mascot/MascotPeek.tsx`**

```typescript
// frontend/src/components/mascot/MascotPeek.tsx
import { useEffect, useState } from 'react'
import { useMascotStore } from '../../stores/mascotStore'
import { MascotSprite } from './MascotSprite'

export function MascotPeek() {
  const enabled = useMascotStore((s) => s.enabled)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!enabled) return

    let lastInteraction = Date.now()

    const trackInteraction = () => {
      lastInteraction = Date.now()
    }
    window.addEventListener('pointermove', trackInteraction, { passive: true })

    const timer = setTimeout(() => {
      const idleMs = Date.now() - lastInteraction
      if (!document.hidden && idleMs >= 30_000) {
        setVisible(true)
        setTimeout(() => setVisible(false), 3300)
      }
    }, 60_000)

    return () => {
      clearTimeout(timer)
      window.removeEventListener('pointermove', trackInteraction)
    }
  }, [enabled])

  if (!visible) return null

  return (
    <div
      className="fixed bottom-0 right-8 z-40 mascot-peek-wrapper"
      aria-hidden="true"
    >
      <MascotSprite size={10} state="idle" />
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors in `MascotPeek.tsx`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/mascot/MascotPeek.tsx
git commit -m "feat: MascotPeek — idle peek from bottom of screen after 60s inactivity"
```

---

## Task 5: Replace TypingIndicator in ChatThread

**Files:**
- Modify: `frontend/src/components/chat/ChatThread.tsx`

The existing `TypingIndicator` function (lines 43–52) is an inline private function. Replace it entirely. When mascot is disabled it renders the original 3 dots; when enabled it renders the walking mascot.

- [ ] **Step 1: Add the import at the top of `ChatThread.tsx`**

After the existing imports (line 8), add:

```typescript
import { MascotSprite } from '../mascot/MascotSprite'
import { useMascotStore } from '../../stores/mascotStore'
```

- [ ] **Step 2: Replace the `TypingIndicator` function (lines 43–52)**

Replace:
```typescript
function TypingIndicator() {
  return (
    <div className="self-start rise-in">
      <div className="card-sand rounded-2xl px-4 py-3.5 flex items-center gap-1.5">
        <span className="typing-dot w-1.5 h-1.5 bg-sage rounded-full" style={{ animationDelay: '0ms' }} />
        <span className="typing-dot w-1.5 h-1.5 bg-sage rounded-full" style={{ animationDelay: '150ms' }} />
        <span className="typing-dot w-1.5 h-1.5 bg-sage rounded-full" style={{ animationDelay: '300ms' }} />
      </div>
    </div>
  )
}
```

With:
```typescript
function TypingIndicator() {
  const mascotEnabled = useMascotStore((s) => s.enabled)
  if (mascotEnabled) {
    return (
      <div className="self-start rise-in">
        <div className="card-sand rounded-2xl px-3 py-2 flex items-end">
          <MascotSprite size={8} state="walk" />
        </div>
      </div>
    )
  }
  return (
    <div className="self-start rise-in">
      <div className="card-sand rounded-2xl px-4 py-3.5 flex items-center gap-1.5">
        <span className="typing-dot w-1.5 h-1.5 bg-sage rounded-full" style={{ animationDelay: '0ms' }} />
        <span className="typing-dot w-1.5 h-1.5 bg-sage rounded-full" style={{ animationDelay: '150ms' }} />
        <span className="typing-dot w-1.5 h-1.5 bg-sage rounded-full" style={{ animationDelay: '300ms' }} />
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Type-check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/chat/ChatThread.tsx
git commit -m "feat: mascot replaces typing indicator in chat (fallback to dots when disabled)"
```

---

## Task 6: Replace LoadingScreen dots in ProtectedLayout

**Files:**
- Modify: `frontend/src/components/layout/ProtectedLayout.tsx`

`LoadingScreen` is defined at the top of the file (lines 8–18). It uses 3 `.typing-dot` spans. Replace those spans with the mascot (or the same dots as fallback).

- [ ] **Step 1: Add the imports at the top of `ProtectedLayout.tsx`**

After `import { useAuthStore } ...` add:

```typescript
import { MascotSprite } from '../mascot/MascotSprite'
import { MascotPeek } from '../mascot/MascotPeek'
import { useMascotStore } from '../../stores/mascotStore'
```

- [ ] **Step 2: Replace the `LoadingScreen` function (lines 8–18)**

Replace:
```typescript
function LoadingScreen({ message }: { message: string }) {
  return (
    <div className="fixed inset-0 bg-surface flex flex-col items-center justify-center gap-5 z-50">
      <div className="flex gap-1.5">
        <span className="typing-dot w-1.5 h-1.5 rounded-full bg-sage" style={{ animationDelay: '0ms' }} />
        <span className="typing-dot w-1.5 h-1.5 rounded-full bg-sage" style={{ animationDelay: '150ms' }} />
        <span className="typing-dot w-1.5 h-1.5 rounded-full bg-sage" style={{ animationDelay: '300ms' }} />
      </div>
      <span className="text-[13px] text-muted">{message}</span>
    </div>
  )
}
```

With:
```typescript
function LoadingScreen({ message }: { message: string }) {
  const mascotEnabled = useMascotStore((s) => s.enabled)
  return (
    <div className="fixed inset-0 bg-surface flex flex-col items-center justify-center gap-5 z-50">
      {mascotEnabled ? (
        <MascotSprite size={12} state="walk" />
      ) : (
        <div className="flex gap-1.5">
          <span className="typing-dot w-1.5 h-1.5 rounded-full bg-sage" style={{ animationDelay: '0ms' }} />
          <span className="typing-dot w-1.5 h-1.5 rounded-full bg-sage" style={{ animationDelay: '150ms' }} />
          <span className="typing-dot w-1.5 h-1.5 rounded-full bg-sage" style={{ animationDelay: '300ms' }} />
        </div>
      )}
      <span className="text-[13px] text-muted">{message}</span>
    </div>
  )
}
```

- [ ] **Step 3: Type-check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/layout/ProtectedLayout.tsx
git commit -m "feat: mascot replaces loading screen dots (fallback to dots when disabled)"
```

---

## Task 7: Mount MascotPeek in ProtectedLayout

**Files:**
- Modify: `frontend/src/components/layout/ProtectedLayout.tsx`

`MascotPeek` should mount once when the app is fully loaded (not during the loading screens). The right place is inside the `return` of `ProtectedLayout` — the Outlet-containing div — so it's only present when the user is authenticated and past the loading phase.

- [ ] **Step 1: Add `<MascotPeek />` inside the ProtectedLayout return**

In `ProtectedLayout.tsx`, find the return block (the one that renders `<Sidebar />` and `<Outlet />`):

```typescript
  return (
    <div className="flex min-h-screen bg-surface text-ink font-sans">
      <Sidebar />
      <main className="flex-1 flex flex-col overflow-hidden pb-20 md:pb-0 h-screen relative">
        <Outlet />
      </main>
      <MobileNav />
    </div>
  )
```

Change it to:

```typescript
  return (
    <div className="flex min-h-screen bg-surface text-ink font-sans">
      <Sidebar />
      <main className="flex-1 flex flex-col overflow-hidden pb-20 md:pb-0 h-screen relative">
        <Outlet />
      </main>
      <MobileNav />
      <MascotPeek />
    </div>
  )
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/layout/ProtectedLayout.tsx
git commit -m "feat: mount MascotPeek in ProtectedLayout for idle peek behaviour"
```

---

## Task 8: Settings toggle

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

Add an "Appearance" card between the Telegram card and the Account Details card (after line 248). The toggle calls `setEnabled` on the mascot store.

- [ ] **Step 1: Add the import at the top of `SettingsPage.tsx`**

Add after the last `import` statement:

```typescript
import { useMascotStore } from '../stores/mascotStore'
```

- [ ] **Step 2: Add store destructuring near the top of the component body**

After `const [saveSuccess, setSaveSuccess] = useState(false)` (around line 38), add:

```typescript
const { enabled: mascotEnabled, setEnabled: setMascotEnabled } = useMascotStore()
```

- [ ] **Step 3: Add the Appearance card in the JSX**

Find the comment `{/* Profile / Account Settings Section */}` (line 250). Directly above it, insert:

```typescript
        {/* Appearance Card */}
        <Card className="border border-sand-border bg-sand backdrop-blur-md">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-sage-deep" />
              Appearance
            </CardTitle>
            <CardDescription>Customise visual flair.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between py-1">
              <div>
                <p className="text-sm font-medium text-ink">Pixel companion</p>
                <p className="text-xs text-muted mt-0.5">
                  A small creature appears while things load
                </p>
              </div>
              <button
                type="button"
                onClick={() => setMascotEnabled(!mascotEnabled)}
                role="switch"
                aria-checked={mascotEnabled}
                className={`relative w-10 h-6 rounded-full transition-colors duration-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sage ${
                  mascotEnabled ? 'bg-sage' : 'bg-sand-border'
                }`}
              >
                <span
                  className={`absolute top-1 w-4 h-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${
                    mascotEnabled ? 'translate-x-5' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>
          </CardContent>
        </Card>
```

- [ ] **Step 4: Type-check + lint**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "feat: Appearance settings card — pixel companion toggle"
```

---

## Task 9: Browser smoke test + final commit

No automated frontend tests exist in this repo; verification is manual + TypeScript.

- [ ] **Step 1: Full type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 2: Start dev server**

```bash
cd frontend && npm run dev
```

Open `http://localhost:5173`.

- [ ] **Step 3: Verify chat loading state (mascot enabled)**

In the chat page, send a message. While the bot responds you should see the terracotta pixel creature walking (two-leg alternating animation) inside the chat bubble instead of 3 dots.

- [ ] **Step 4: Verify startup loading screen**

Hard-refresh the page (`Ctrl+Shift+R`). During the "Syncing session…" screen you should see a larger walking mascot (size=12, ~48px wide) instead of dots.

- [ ] **Step 5: Verify Settings toggle**

Go to Settings. Find the "Appearance" card. Toggle "Pixel companion" off — the toggle slides left and turns grey. Refresh the page. The loading screen should show the original 3 dots. Send a message — chat indicator should show 3 dots. Toggle back on.

- [ ] **Step 6: Verify peek does NOT fire for active users**

Move the mouse continuously for 2 minutes. The creature should not peek (idle guard: ≥ 30 s without `pointermove`). To manually test peek: open browser console and run `window.dispatchEvent(new Event('...'))`... actually just wait 60 s without touching the mouse after page load.

- [ ] **Step 7: Verify reduced-motion**

In browser DevTools → Rendering → Emulate CSS media: `prefers-reduced-motion: reduce`. Reload. The mascot should be visible but all animations stopped (the existing `index.css` rule sets `animation-duration: 0.01ms !important` for all elements).

- [ ] **Step 8: Close GitHub issue**

```bash
gh issue comment 13 --repo AswinManohar/nutrichat \
  --body "Implemented across commits in Task 1–8. MascotSprite SVG component, walk/idle/peek CSS animations, Settings toggle, chat typing indicator and startup loading screen updated."
gh issue close 13 --repo AswinManohar/nutrichat
```
