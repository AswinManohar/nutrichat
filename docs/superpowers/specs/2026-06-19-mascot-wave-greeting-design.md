# Mascot Wave Greeting — Design Spec

**Date:** 2026-06-19
**Status:** Approved

---

## Overview

When the chat thread is empty and the mascot is enabled, the mascot appears above the input bar waving hello. It disappears the moment the first message enters the thread. No text accompanies it — the waving figure speaks for itself.

---

## Behaviour

| Condition | State |
|---|---|
| `messages.length === 0` AND `mascotStore.enabled === true` | Mascot visible, waving |
| `messages.length > 0` OR `mascotStore.enabled === false` | Mascot hidden (exit transition plays) |

The mascot is hidden — not unmounted immediately — so the exit animation has time to play before the element leaves the DOM. A 200ms fade + slide-down on exit is sufficient.

---

## Placement

`ChatPage` renders the mascot as a `flex-shrink-0` block between `<ChatThread>` and `<ChatInput>`. The thread is `flex-1` and scrollable; the mascot sits in the fixed gap below it. On a fresh session the thread is empty and the mascot fills that space naturally above the input pill.

No changes to `ChatThread` or `ChatInput`.

---

## Animation

### New `wave` variant

A double-wave gesture followed by a hold, then repeat. Applied to the whole sprite since the mascot is a single `.webm` element.

```css
@keyframes mascot-wave {
  0%         { transform: rotate(0deg)    translateY(0);    }
  10%        { transform: rotate(15deg)   translateY(-4px); }
  20%        { transform: rotate(-8deg)   translateY(0);    }
  30%        { transform: rotate(15deg)   translateY(-4px); }
  40%, 100%  { transform: rotate(0deg)    translateY(0);    }
}

.mascot-wave {
  transform-origin: bottom center;
  animation: mascot-wave 2.8s ease-in-out infinite;
}
```

The wave fires at 0–40% of the cycle; 40–100% is a natural pause before the next wave. At 2.8s per cycle this feels energetic but not frantic.

`prefers-reduced-motion` is already handled globally in `index.css` (all animations collapse to 0.01ms / 1 iteration), so no extra work needed here.

### Entry / exit

| Direction | Behaviour |
|---|---|
| Entry (on mount) | Fade in + slide up 8px, 250ms ease-out |
| Exit (messages arrive) | Fade out + slide down 8px, 200ms ease-out |

Exit is driven by a CSS class toggle on a `show` prop, with a `transitionend` listener (or a fixed `setTimeout(200)`) before unmounting.

---

## Component: `MascotGreeting`

**File:** `frontend/src/components/mascot/MascotGreeting.tsx`

```
Props:
  show: boolean   — true when messages.length === 0

Behaviour:
  - Reads useMascotStore(s => s.enabled)
  - If !enabled, returns null immediately (no DOM node)
  - When show flips false, plays exit transition then removes itself
  - Renders MascotSprite size={14} variant="wave"
  - Centred horizontally, aligned to the bottom of the available space
    above the input (pb-4 to breathe off the input border)
```

Size 14 (`56px`) — large enough to read as a deliberate greeting, small enough not to crowd the input pill.

---

## Files changed

| File | Change |
|---|---|
| `frontend/src/index.css` | Add `@keyframes mascot-wave` + `.mascot-wave` |
| `frontend/src/components/mascot/MascotSprite.tsx` | Add `'wave'` to variant union |
| `frontend/src/components/mascot/MascotGreeting.tsx` | New component |
| `frontend/src/pages/ChatPage.tsx` | Render `<MascotGreeting show={messages.length === 0} />` |

---

## Out of scope

- No greeting text or speech bubble
- No click / tap interaction on the mascot
- No new mascot store state (reuses existing `enabled` flag)
- No changes to `MascotPeek` or its idle-detection logic
