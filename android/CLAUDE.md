# CLAUDE.md — Mealsy Android design system

This is the Android-adapted version of `android/design-handoff/DESIGN_SYSTEM_SPEC.md`
and `android/design-handoff/README.md`. All new UI in this project MUST follow
this system. The `.html` files in `android/design-handoff/` are the reference
prototypes — their inline `style=""` attributes carry the authoritative pixel
specs (colors, sizes, radii). Read the relevant `.html` before implementing a
screen or component; this document translates that spec into Compose terms.

All px in the handoff → dp (spacing/sizes) or sp (text). All CSS custom
properties → the Compose token names below, exposed by `:core:ui`.

---

## Design tokens

### `MealsyColors` — light

| Property | Hex | Use |
|---|---|---|
| `canvas` | `#F6F1E1` | Screen background everywhere |
| `surface` | `#EBE5D0` | Cards, list containers, coach notes, coach chat bubble |
| `surfacePressed` | `#E2DBC4` | Pressed state of surface rows/cards |
| `divider` | `#DDD5BC` | Hairlines inside surface containers, section borders |
| `hairline` | `#C9C2A9` | Outlined buttons, inputs, chips, stepper borders |
| `ink` | `#1C1B17` | Display text, primary buttons, count badges, bottom nav |
| `inkPressed` | `#3A3830` | Pressed primary button |
| `muted` | `#6F6A58` | Labels, secondary text, eyebrows |
| `inactive` | `#8B887C` | Inactive nav icons, placeholders, chevrons, timestamps |
| `olive` | `#A6B565` | Hero status element (exactly ONE per screen), FAB, toggle-on, progress fill, sparkle icon |
| `oliveText` | `#2A3013` | Text on olive |
| `oliveTrack` | `#DEE2C3` | Progress track, "eaten" part of snack bar, totals strip |
| `olivePressed` | `#96A45B` | Pressed olive |
| `userBubble` | `#DCE3BE` | User chat bubble (text `#2A3013`) |
| `butter` / `butterText` | `#F2D45C` / `#4A3A08` | Pastel chip |
| `pink` / `pinkText` | `#F0A9C6` / `#5A1F3A` | Pastel chip |
| `leaf` / `leafText` | `#A9C46F` / `#2A3013` | Pastel chip |
| `powder` / `powderText` | `#A9C0E4` / `#1E3050` | Pastel chip |
| `terracotta` / `terracottaText` | `#BE7250` / `#3F2012` | Destructive filled |
| `terracottaOutlineText` | `#A85B3B` | Destructive outlined variant text |

Pastels are for 32–36dp icon circles and tiny metadata tags ONLY — never
fills, backgrounds, or buttons. Text on any colored fill is a darker shade of
the same hue, never black/gray. No gradients. No shadows anywhere except the
FAB (`0dp 4dp 14dp rgba(28,27,23,0.28)`). No pure white or black. Screens are
~90% cream/beige/ink; exactly ONE full-width olive status element per screen
(no status → no olive).

### `MealsyColors` — dark

| Property | Hex |
|---|---|
| `canvas` | `#201F1A` |
| `surface` | `#2B2A23` |
| `divider` | `#3A382E` |
| `ink` | `#F6F1E1` (flips to cream) |
| `muted` | `#A8A493` |
| `inactive` | `#7A776B` |
| `butter` | `#D9BE53` |
| `pink` | `#D898B2` |
| `leaf` | `#98B064` |
| `powder` | `#98ACCD` |
| `olive` | `#96A45B` (text `#1E230D`) |

Bottom nav stays ink (`#1C1B17`) with a 1dp `#3A382E` hairline border in dark
mode too. FAB always stays `#A6B565` regardless of theme. Full dark token
sheet is rendered in `android/design-handoff/Mealsy Design System.html`
(section "Dark mode") — treat that as the source of truth for any pastel-text
color not listed above.

### `MealsyType` — Geist (single family, weights 400–800)

Bundle Geist as an Android font resource in `:core:ui`'s
`src/main/res/font/`. Enable tabular numerals
(`fontFeatureSettings = "tnum"`) on every numeric style.

| Role | Size / line | Weight | Extras |
|---|---|---|---|
| `hero` | 46sp / 1.02 | 600–700 | uppercase, letterSpacing −0.02em |
| `display` | 28–34sp / 1.1 | 500 | letterSpacing −0.02em, may wrap 2 lines |
| `screenTitle` | 30sp / 1.12 | 500 | letterSpacing −0.02em |
| `section` | 17–18sp | 500 | |
| `body` | 14sp / 1.5 | 400 | |
| `label` | 12–13sp | 400 | color `muted` |
| `eyebrow` | 11sp | 500 | uppercase, letterSpacing 0.12em, color `muted` |
| `button` | 15sp | 500 | |
| `badge` / `tinyTag` | 12sp (10sp for tiny tags) | 500 | |
| `bigNumber` | 19–26sp | 500–700 | tabular figures |

### `MealsyShapes`

| Property | Radius |
|---|---|
| `phone` | 26dp (phone container, reference only — not used in-app) |
| `card` | 18dp (cards/containers) |
| `pill` | 999dp (pills/badges/buttons/nav/inputs) |
| `strip` | 14dp (totals strip, small icon-chip tiles) |

Icon chips are perfect circles (`CircleShape`), not `MealsyShapes`.

### Spacing

8dp grid. Screen horizontal margins 18–22dp (20dp default, 24dp onboarding).
Content top padding ~60–64dp below the status bar
(`WindowInsets.statusBars` + 24dp). List rows 44–52dp min height. Card
padding 14–20dp. Grid/card gap 10dp. Section gap 20–28dp.

### Motion

Calm, no bounce. 150ms ease for selection fills. 250–400ms ease-out for
width/position changes (progress bar, snack-bar bite). Toast slides up
250ms. Mascot idle "bob": translateY 0→−8dp, 3.2s ease-in-out infinite.

---

## Cross-cutting rules

- Exactly ONE olive element per screen. No status to show → no olive element.
- Pastels (butter/pink/leaf/powder) are for 32–36dp icon circles and tiny
  metadata tags ONLY. Never as fills, backgrounds, or button colors.
- No shadows anywhere except the FAB
  (`0dp 4dp 14dp rgba(28,27,23,0.28)`).
- No pure white or pure black anywhere (use `ink`/`canvas`, not `#000`/`#FFF`).
- No gradients.
- Geist everywhere — no other font family.
- Tabular numerals (`fontFeatureSettings = "tnum"`) on all numeric styles
  (`bigNumber`, badges, metric values, chat metadata tags, totals strip).
- 8dp grid for all spacing and sizing decisions.
- Every interactive element gets a `contentDescription` (icons) or
  equivalent semantics (`Modifier.semantics`, `role`) — this is not optional.
- Every public composable gets Google-style KDoc.
- Every component gets `@Preview` for both light and dark, plus a Roborazzi
  golden screenshot test (goldens land in `core/ui/src/test/screenshots/`,
  see `android/core/ui/build.gradle.kts`).
- All user-facing copy goes in `res/values/strings.xml` — never inline
  string literals in composables.

## Voice (copy rules)

Short, specific, second person. Explain why, suggest one concrete action,
never scold. No exclamation marks. No streak pressure. No diagnoses.
Sentence case for labels; uppercase only for eyebrows and the welcome
headline.

## Mascot (Olli)

`assets/mascot.webm` (transparent, loop, muted). Allowed ONLY on:
onboarding, empty states, chat header, snack-bar bite point. Never elsewhere
on data screens. Ship as WebM (VP9 with alpha) via Media3, or export to
Lottie/animated WebP (animated WebP rendering needs `ImageDecoder`, API 28 —
this is why `minSdk` is 28, not 26).

---

## Where things live

- `android/core/ui/src/main/java/app/mealsy/android/design/theme/` — colors,
  type, shapes (`MealsyColors`, `MealsyType`, `MealsyShapes`, the theme
  composable). Owned by task T2.
- `android/core/ui/src/main/java/app/mealsy/android/design/components/` —
  shared components (list row, coach note, metric card, progress ring,
  buttons, meal card, chat bubbles, pill input, toggle, toast, segmented
  control, stepper, tag chip, bottom nav + FAB).
- `android/core/ui/src/main/java/app/mealsy/android/design/icons/` — 24-grid
  stroked line `ImageVector`s (1.8–2dp stroke, round caps), recreated from
  the inline SVG paths in the `.html` files.
- `android/core/ui/src/main/java/app/mealsy/android/design/mascot/` — Olli
  playback (Media3/Coil-gif wrapper).
- `android/core/ui/src/main/res/font/` — bundled Geist font files.
- `android/core/ui/src/main/res/raw/` — bundled `mascot.webm` (or converted
  asset) for playback.
- `android/design-handoff/` — the design reference bundle. Read before
  implementing any screen:
  - `Mealsy Design System.html` — tokens (light + dark), full component
    library with states, and four phone screens (Onboarding welcome, Home,
    Meal detail, Coach chat). Start here.
  - `Mealsy Onboarding.html` — interactive 6-state onboarding flow.
  - `Meal Confirm Card.html` — interactive confirm card.
  - `Meal Type Selector Options.html` — meal-type selector variants
    (segmented variant 1b was chosen).
  - `Mealsy Landing Page.html` — web marketing reference only, not part of
    the Android app.
  - `README.md` / `DESIGN_SYSTEM_SPEC.md` — the full written spec this file
    condenses for Android.
  - `assets/mascot.webm`, `assets/meatballs.jpg` — mascot animation and
    placeholder meal photo.

The `.html` files' inline `style=""` values are authoritative for exact
pixel specs (colors, sizes, radii, spacing) — when this document and an
`.html` file disagree, the `.html` file wins; update this file to match.
