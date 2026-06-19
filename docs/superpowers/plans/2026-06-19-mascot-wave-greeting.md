# Mascot Wave Greeting — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the mascot above the chat input waving hello when the thread is empty; hide it once the first message arrives.

**Architecture:** Add a `wave` CSS animation variant, extend `MascotSprite`'s variant union, create a self-contained `MascotGreeting` component that reads `useMascotStore`, and mount it in `ChatPage` between the thread and input.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, CSS keyframes, Zustand

## Global Constraints

- No test framework in frontend — verification is TypeScript type-check (`npm run build --prefix frontend`) + visual browser check
- Respect `useMascotStore(s => s.enabled)` — render nothing when `false`
- `prefers-reduced-motion` is handled globally in `index.css` (all animations → 0.01ms / 1 iteration); no extra work needed per component
- Use `setTimeout` (not `transitionend`) for exit unmount — simpler and avoids edge cases with interrupted transitions
- Size: `MascotSprite size={14}` (56 × 56 px)
- Do not modify `MascotPeek`, `ChatThread`, or `ChatInput`

---

### Task 1: Add `mascot-wave` CSS animation

**Files:**
- Modify: `frontend/src/index.css`

**Interfaces:**
- Produces: `.mascot-wave` CSS class, usable as `variant="wave"` class name in `MascotSprite`

- [ ] **Step 1: Open `frontend/src/index.css` and add the keyframe + class after `.mascot-sway` block**

Find this block (ends around the `.mascot-sway` rule):
```css
.mascot-sway {
  transform-origin: bottom center;
  animation: mascot-sway 1.4s ease-in-out infinite;
}
```

Insert immediately after it:
```css
/* Empty-state greeting: double wave then hold */
@keyframes mascot-wave {
  0%        { transform: rotate(0deg)  translateY(0);    }
  10%       { transform: rotate(15deg) translateY(-4px); }
  20%       { transform: rotate(-8deg) translateY(0);    }
  30%       { transform: rotate(15deg) translateY(-4px); }
  40%, 100% { transform: rotate(0deg)  translateY(0);    }
}
.mascot-wave {
  transform-origin: bottom center;
  animation: mascot-wave 2.8s ease-in-out infinite;
}
```

- [ ] **Step 2: Verify type-check passes**

```bash
npm run build --prefix /home/aswinmanohar/nutrichat/frontend 2>&1 | tail -5
```
Expected: build succeeds (CSS change, no TS errors introduced).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/index.css
git commit -m "feat(mascot): add mascot-wave CSS animation"
```

---

### Task 2: Add `wave` to `MascotSprite` variant union

**Files:**
- Modify: `frontend/src/components/mascot/MascotSprite.tsx`

**Interfaces:**
- Consumes: `.mascot-wave` CSS class from Task 1
- Produces: `MascotSprite` accepts `variant="wave"`

- [ ] **Step 1: Update the variant type and component**

Replace the entire file content:
```tsx
interface MascotSpriteProps {
  size?: number
  variant?: 'jump' | 'bounce' | 'sway' | 'wave'
  className?: string
}

export function MascotSprite({ size = 10, variant, className }: MascotSpriteProps) {
  const px = size * 4
  const variantClass = variant ? `mascot-${variant}` : ''
  return (
    <video
      src="/mascot.webm"
      width={px}
      height={px}
      autoPlay
      loop
      muted
      playsInline
      aria-hidden="true"
      className={[variantClass, className].filter(Boolean).join(' ') || undefined}
      style={{ display: 'block', objectFit: 'contain' }}
    />
  )
}
```

- [ ] **Step 2: Verify type-check passes**

```bash
npm run build --prefix /home/aswinmanohar/nutrichat/frontend 2>&1 | tail -5
```
Expected: build succeeds, no TS errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/mascot/MascotSprite.tsx
git commit -m "feat(mascot): add wave variant to MascotSprite"
```

---

### Task 3: Create `MascotGreeting` component

**Files:**
- Create: `frontend/src/components/mascot/MascotGreeting.tsx`

**Interfaces:**
- Consumes: `useMascotStore` from `../../stores/mascotStore`, `MascotSprite` with `variant="wave"` (Task 2)
- Produces: `<MascotGreeting show={boolean} />` — renders the waving mascot when `show && enabled`, plays exit transition on `show → false`

- [ ] **Step 1: Create the file**

```tsx
import { useEffect, useRef, useState } from 'react'
import { useMascotStore } from '../../stores/mascotStore'
import { MascotSprite } from './MascotSprite'

interface MascotGreetingProps {
  show: boolean
}

export function MascotGreeting({ show }: MascotGreetingProps) {
  const enabled = useMascotStore((s) => s.enabled)
  const [mounted, setMounted] = useState(show && enabled)
  const [visible, setVisible] = useState(show && enabled)
  const exitTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!enabled) {
      setVisible(false)
      setMounted(false)
      return
    }
    if (show) {
      setMounted(true)
      // Tiny delay so the browser registers the initial state before
      // the visible class triggers the enter transition.
      requestAnimationFrame(() => setVisible(true))
    } else {
      setVisible(false)
      exitTimer.current = setTimeout(() => setMounted(false), 200)
    }
    return () => {
      if (exitTimer.current) clearTimeout(exitTimer.current)
    }
  }, [show, enabled])

  if (!mounted) return null

  return (
    <div
      className="flex justify-center pb-4 transition-all duration-200 ease-out"
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(8px)',
      }}
      aria-hidden="true"
    >
      <MascotSprite size={14} variant="wave" />
    </div>
  )
}
```

- [ ] **Step 2: Verify type-check passes**

```bash
npm run build --prefix /home/aswinmanohar/nutrichat/frontend 2>&1 | tail -5
```
Expected: build succeeds, no TS errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/mascot/MascotGreeting.tsx
git commit -m "feat(mascot): MascotGreeting component — waving empty-state greeting"
```

---

### Task 4: Mount `MascotGreeting` in `ChatPage`

**Files:**
- Modify: `frontend/src/pages/ChatPage.tsx`

**Interfaces:**
- Consumes: `<MascotGreeting show={boolean} />` from Task 3
- `messages` already available from `useMealStore` in scope

- [ ] **Step 1: Add the import**

In `frontend/src/pages/ChatPage.tsx`, add after the existing mascot/chat imports:
```tsx
import { MascotGreeting } from '../components/mascot/MascotGreeting'
```

- [ ] **Step 2: Mount the component**

Find this block in the JSX (inside the chat column `<div>`):
```tsx
        <ChatThread
          messages={messages}
```

Insert `<MascotGreeting>` immediately before it:
```tsx
        <MascotGreeting show={messages.length === 0} />
        <ChatThread
          messages={messages}
```

- [ ] **Step 3: Verify type-check passes**

```bash
npm run build --prefix /home/aswinmanohar/nutrichat/frontend 2>&1 | tail -5
```
Expected: build succeeds, no TS errors.

- [ ] **Step 4: Visual check in browser**

```bash
cd /home/aswinmanohar/nutrichat/frontend && npm run dev &
```

Open `http://localhost:5173/chat`:
1. Fresh/empty thread → mascot visible, waving animation plays (double wave + hold cycle)
2. Send any message → mascot fades out and slides down (200ms), disappears
3. Disable mascot in Settings → mascot does not appear even on empty thread
4. Re-enable mascot → mascot reappears on next empty thread visit

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ChatPage.tsx
git commit -m "feat(mascot): show waving greeting above input on empty thread"
```
