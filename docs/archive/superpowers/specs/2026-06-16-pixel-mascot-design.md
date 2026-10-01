# Pixel Mascot — Design Spec
**Date:** 2026-06-16
**Status:** Approved
**Scope:** A terracotta pixel creature that replaces the existing typing-dot animations
on two surfaces (chat loading, startup loading screen) and makes rare idle appearances.
Disable toggle in Settings.

---

## 1. Character Design

The mascot is a 10×12 "pixel" grid rendered as SVG `<rect>` elements.
Each logical pixel is 4 CSS px (scales via `size` prop). The SVG viewBox is `0 0 40 52`.

### 1.1 Pixel grid (`.` = transparent, `B` = body, `E` = eye, `L` = leg)

```
Col →  0  1  2  3  4  5  6  7  8  9
Row 0  .  .  B  B  B  B  B  B  .  .     ← body top (8 wide)
Row 1  .  B  B  B  B  B  B  B  B  .     ← shoulders
Row 2  .  B  B  B  B  B  B  B  B  .
Row 3  .  B  E  E  B  B  E  E  B  .     ← eyes (2 wide, 1 tall, spaced)
Row 4  .  B  B  B  B  B  B  B  B  .
Row 5  .  B  B  B  B  B  B  B  B  .
Row 6  .  B  B  B  B  B  B  B  B  .
Row 7  .  .  B  B  B  B  B  B  .  .     ← body bottom (8 wide, tapers)
Row 8  .  .  L  L  .  .  L  L  .  .     ← legs
Row 9  .  .  L  L  .  .  L  L  .  .
Row 10 .  .  L  L  .  .  L  L  .  .
Row 11 .  .  L  L  .  .  L  L  .  .     ← feet
```

### 1.2 Colours

| Role | Hex | Usage |
|---|---|---|
| Body | `#C47A4A` | Main terracotta body & legs |
| Body shadow | `#A55E32` | Bottom 2 rows of body (slight depth) |
| Eye | `#1A1A1A` | Eyes (near-black) |
| Eye shine | `#FFFFFF` | 1×1 pixel highlight inside each eye |

### 1.3 SVG rect map (pixel = 4×4 units)

```
x = col * 4,  y = row * 4,  width = 4,  height = 4
```

Body rects (terracotta `#C47A4A`): all B cells rows 0–6
Body rects (shadow `#A55E32`): B cells rows 7 (tapered bottom)
Leg rects (`#C47A4A`): L cells rows 8–11
Eye rects (`#1A1A1A`): col 2–3 row 3, col 6–7 row 3 (each 8×4 units)
Eye shine (`#FFFFFF`): 2×2 at top-left corner of each eye rect

---

## 2. Animation States

### 2.1 Walk cycle (used in TypingIndicator + LoadingScreen)

4-frame CSS animation, 400 ms/frame (total 1600 ms, `infinite`).

| Frame | Left leg | Right leg | Body |
|---|---|---|---|
| 0 — contact | `translateY(0)` | `translateY(-4px)` | `translateY(0)` |
| 1 — mid | `translateY(0)` | `translateY(0)` | `translateY(-1px)` |
| 2 — contact | `translateY(-4px)` | `translateY(0)` | `translateY(0)` |
| 3 — mid | `translateY(0)` | `translateY(0)` | `translateY(-1px)` |

Implemented as two `@keyframes` blocks:
- `mascot-leg-left` (applied to left-leg `<g>`)
- `mascot-leg-right` (applied to right-leg `<g>`, 800 ms phase offset = `animation-delay: -800ms`)
- `mascot-body-bob` (applied to body `<g>`, subtle ±1 px)

### 2.2 Blink (used in idle state)

Eyelid = additional `#C47A4A` rect (4×3 units) overlaid on each eye. Normally
`scaleY(0)`, animates to `scaleY(1)` briefly every 3 seconds.

```css
@keyframes mascot-blink {
  0%, 92%, 100%  { transform: scaleY(0); }
  94%, 98%       { transform: scaleY(1); }
}
```

### 2.3 Idle peek (rare bottom-edge appearance)

A fixed-position `<div>` at `bottom: 0`, starts `translateY(100%)` (fully hidden
below viewport), animates to `translateY(calc(100% - 36px))` (head + eyes visible),
holds 2 s, then slides back down. Fires once per session, ~60 s after first load,
only if the user hasn't interacted with the page for ≥30 s.

```css
@keyframes mascot-peek {
  0%   { transform: translateY(100%); }
  15%  { transform: translateY(calc(100% - 36px)); }   /* peek position */
  80%  { transform: translateY(calc(100% - 36px)); }   /* hold */
  100% { transform: translateY(100%); }
}
```

The peek renders the mascot in `idle` state (body + eyes, no walk, blink active).

---

## 3. React Component

### 3.1 `MascotSprite` (`frontend/src/components/mascot/MascotSprite.tsx`)

```typescript
interface MascotSpriteProps {
  size?: number       // logical-pixel size (default: 10); rendered width = size * 4 CSS px
  state?: 'walk' | 'idle' | 'peek'
  className?: string
}
```

- Renders an inline `<svg viewBox="0 0 40 52">` with grouped elements:
  - `<g className="mascot-body">` — body rects
  - `<g className="mascot-left-leg">` — left leg L-cells
  - `<g className="mascot-right-leg">` — right leg L-cells
  - `<g className="mascot-eyes">` — eye rects + shine
  - `<g className="mascot-eyelids">` — eyelid rects (blink)
- When `state === 'walk'`: applies `mascot-leg-left`, `mascot-leg-right`, `mascot-body-bob`.
- When `state === 'idle'`: applies `mascot-blink` on eyelids only.
- When `state === 'peek'`: same as idle (no walk cycle).
- Respects `prefers-reduced-motion`: all animations set to `animation: none` inside the `@media (prefers-reduced-motion: reduce)` block already in `index.css`.

### 3.2 CSS (`frontend/src/index.css` additions)

All new keyframes added inside `index.css` under a `/* Pixel mascot animations */` comment block. The `.mascot-*` classes reference the keyframes. No new CSS files.

---

## 4. Settings Preference

### 4.1 `useMascotStore` (`frontend/src/stores/mascotStore.ts`)

Simple Zustand store, persisted to `localStorage`:

```typescript
interface MascotState {
  enabled: boolean
  setEnabled: (v: boolean) => void
}
```

`enabled` defaults to `true`. All mascot surfaces read `useMascotStore(s => s.enabled)`;
when `false`, they fall back to the original `typing-dot` 3-dot animation.

### 4.2 Settings UI

A new row in `SettingsPage.tsx` under a "Appearance" section:
- Label: "Pixel companion"
- Sub-label: "A small creature hangs out while things load"
- Toggle control (same `<Switch>` component used elsewhere in settings)

---

## 5. Surface Changes

### 5.1 Chat typing indicator (`ChatThread.tsx:43`)

Replace the inline `TypingIndicator` function with:

```typescript
import { MascotSprite } from '../mascot/MascotSprite'
import { useMascotStore } from '../../stores/mascotStore'

function TypingIndicator() {
  const mascotEnabled = useMascotStore(s => s.enabled)
  if (mascotEnabled) {
    return (
      <div className="flex items-end gap-2 px-4 py-2">
        <MascotSprite size={8} state="walk" />
      </div>
    )
  }
  return (
    <div className="flex gap-1.5 px-4 py-2 items-center">
      <span className="typing-dot w-1.5 h-1.5 bg-sage rounded-full" style={{ animationDelay: '0ms' }} />
      <span className="typing-dot w-1.5 h-1.5 bg-sage rounded-full" style={{ animationDelay: '150ms' }} />
      <span className="typing-dot w-1.5 h-1.5 bg-sage rounded-full" style={{ animationDelay: '300ms' }} />
    </div>
  )
}
```

### 5.2 Startup loading screen (`ProtectedLayout.tsx:8`)

Replace the `LoadingScreen` function's dot block:

```typescript
import { MascotSprite } from '../mascot/MascotSprite'
import { useMascotStore } from '../../stores/mascotStore'

function LoadingScreen({ message }: { message: string }) {
  const mascotEnabled = useMascotStore(s => s.enabled)
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

### 5.3 Idle peek (`MascotPeek.tsx` + `App.tsx`)

New `MascotPeek` component renders a `fixed bottom-0 right-8` div hosting `MascotSprite state="peek"`. Mounts once in `App.tsx` (or `ProtectedLayout`), reads `mascotEnabled`, fires the animation via a `useEffect` timer:
- Delay: 60 s after mount
- Guard: only if `document.hidden === false` and `Date.now() - lastInteraction > 30_000`
- Tracks `lastInteraction` via a `pointermove` listener on `window` (set once on mount).
- After animation completes (3 s animation), unmounts itself via state to avoid a persistent DOM node.

```typescript
// MascotPeek.tsx
export function MascotPeek() {
  const enabled = useMascotStore(s => s.enabled)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!enabled) return
    let lastInteraction = Date.now()
    const trackInteraction = () => { lastInteraction = Date.now() }
    window.addEventListener('pointermove', trackInteraction, { passive: true })

    const timer = setTimeout(() => {
      if (!document.hidden && Date.now() - lastInteraction > 30_000) {
        setVisible(true)
        setTimeout(() => setVisible(false), 3200)  // matches animation duration
      }
    }, 60_000)

    return () => {
      clearTimeout(timer)
      window.removeEventListener('pointermove', trackInteraction)
    }
  }, [enabled])

  if (!visible) return null
  return (
    <div className="fixed bottom-0 right-8 z-40" style={{ animation: 'mascot-peek 3.2s ease-in-out forwards' }}>
      <MascotSprite size={10} state="idle" />
    </div>
  )
}
```

---

## 6. File Map

| File | Change |
|---|---|
| `frontend/src/components/mascot/MascotSprite.tsx` | New: SVG pixel art + walk/idle/peek state |
| `frontend/src/components/mascot/MascotPeek.tsx` | New: idle peek timer component |
| `frontend/src/stores/mascotStore.ts` | New: `useMascotStore` (enabled flag, localStorage) |
| `frontend/src/index.css` | Add `mascot-*` keyframes + classes |
| `frontend/src/components/chat/ChatThread.tsx` | Replace `TypingIndicator` to use mascot |
| `frontend/src/components/layout/ProtectedLayout.tsx` | Replace `LoadingScreen` dots |
| `frontend/src/App.tsx` (or `ProtectedLayout.tsx`) | Mount `<MascotPeek />` once |
| `frontend/src/pages/SettingsPage.tsx` | "Pixel companion" toggle |

---

## 7. Testing

| Test | How |
|---|---|
| `MascotSprite` renders without errors | TypeScript `tsc --noEmit` + browser render smoke |
| Walk / idle / peek state props apply correct CSS classes | Unit test with `@testing-library/react` (if test infra exists) |
| `useMascotStore` persists `enabled=false` across reload | Manual: toggle off → refresh → still off |
| Fallback to dots when `enabled=false` | Manual: confirm 3-dot animation returns |
| `MascotPeek` does NOT fire if user is active | Manual: wiggle mouse during 60 s window → no peek |
| `prefers-reduced-motion` disables all animations | Browser devtools emulation |

---

## 8. Out of Scope (V1)

- Custom mascot skins or colours.
- Mascot reacting to specific events (e.g. happy animation on goal hit).
- Multiple idle behaviours (currently just one peek; additional animations are follow-ups).
- Mobile-specific mascot positions (peek appears bottom-right on all viewports).
