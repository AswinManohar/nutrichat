# Handoff: Mealsy — Android front end

## Overview
Mealsy is an AI nutrition coach. The user logs meals in plain words or photos; the coach ("Olli", the mascot) returns nutrition, a daily status, and one concrete suggestion. This package covers the complete mobile design system plus five screens/flows, to be implemented as a **native Android app** talking to the existing `nutrichat` FastAPI backend.

The backend already exists (`nutrichat/src/backend`, Python/FastAPI, Supabase auth). The existing React web client (`nutrichat/frontend/src`) is a useful reference for API usage (`api/client.ts`, `api/types.ts`, `api/hooks.ts`) but its visual design is NOT the target — this package is.

## About the Design Files
The `.html` files in this bundle are **design references built in HTML** — interactive prototypes showing intended look and behavior. They are not production code. The task is to **recreate these designs in Android** using the project's chosen stack. Recommendation: **Kotlin + Jetpack Compose + Material 3** with a custom theme (colors, type, shapes below), Navigation Compose, Retrofit/Ktor + kotlinx.serialization, Coil for images, Media3/ExoPlayer for the mascot loop. Read the HTML for exact values; the inline `style=""` attributes are the spec.

Open the HTML files in a browser to interact with them (steppers, tabs, sliders, chat, onboarding steps all work).

## Fidelity
**High-fidelity.** Colors, typography, spacing, radii, and copy are final. Recreate pixel-close at 390dp width (iPhone frame in the mocks ≈ 390×844; treat as a 390dp Android reference and let layouts stretch horizontally). Where the mocks show iOS chrome (status bar, home indicator), use Android system UI instead.

---

## Design tokens

### Colors — light
| Token | Hex | Use |
|---|---|---|
| canvas | `#F6F1E1` | Screen background everywhere |
| surface | `#EBE5D0` | Cards, list containers, coach notes, coach chat bubble |
| surfacePressed | `#E2DBC4` | Pressed state of surface rows/cards |
| divider | `#DDD5BC` | Hairlines inside surface containers, section borders |
| hairline | `#C9C2A9` | Outlined buttons, inputs, chips, stepper borders |
| ink | `#1C1B17` | Display text, primary buttons, count badges, bottom nav |
| inkPressed | `#3A3830` | Pressed primary button |
| muted | `#6F6A58` | Labels, secondary text, eyebrows |
| inactive | `#8B887C` | Inactive nav icons, placeholders, chevrons, timestamps |
| olive | `#A6B565` | Hero status element (exactly ONE per screen), FAB, toggle-on, progress fill, sparkle icon |
| oliveText | `#2A3013` | Text on olive |
| oliveTrack | `#DEE2C3` | Progress track, "eaten" part of snack bar, totals strip |
| olivePressed | `#96A45B` | Pressed olive |
| userBubble | `#DCE3BE` | User chat bubble (text `#2A3013`) |
| butter | `#F2D45C` / text `#4A3A08` | Pastel chip |
| pink | `#F0A9C6` / text `#5A1F3A` | Pastel chip |
| leaf | `#A9C46F` / text `#2A3013` | Pastel chip |
| powder | `#A9C0E4` / text `#1E3050` | Pastel chip |
| terracotta | `#BE7250` / text `#3F2012` | Destructive filled; outlined variant text `#A85B3B` |

Pastels are for 32–36dp icon circles and tiny metadata tags ONLY — never fills, backgrounds, or buttons. Text on any colored fill is a darker shade of the same hue, never black/gray. No gradients. No shadows except the FAB (`0 4dp 14dp rgba(28,27,23,0.28)`). No pure white or black.

### Colors — dark
canvas `#201F1A`, surface `#2B2A23`, divider `#3A382E`, ink→`#F6F1E1`, muted `#A8A493`, inactive `#7A776B`. Pastels: butter `#D9BE53`, pink `#D898B2`, leaf `#98B064`, powder `#98ACCD`. Olive `#96A45B` (text `#1E230D`). Bottom nav stays ink `#1C1B17` with a 1dp `#3A382E` border; FAB stays `#A6B565`. Full dark token sheet is rendered in `Mealsy Design System.html` (section "Dark mode").

### Typography — Geist (single family)
Bundle Geist from Google Fonts (variable, weights 400–800) as an Android font resource.
| Role | Size / line | Weight | Extras |
|---|---|---|---|
| Hero welcome | 46sp / 1.02 | 600–700 | uppercase, tracking −0.02em |
| Display | 28–34sp / 1.1 | 500 | tracking −0.02em, may wrap 2 lines |
| Screen title (onboarding) | 30sp / 1.12 | 500 | tracking −0.02em |
| Section header | 17–18sp | 500 | |
| Body | 14sp / 1.5 | 400 | |
| Label | 12–13sp | 400 | color muted |
| Eyebrow | 11sp | 500 | uppercase, tracking 0.12em, color muted |
| Button | 15sp | 500 | |
| Badge / tag | 12sp (10sp for tiny tags) | 500 | |
| Big number | 19–26sp | 500–700 | tabular figures |
All numerals: `fontFeatureSettings = "tnum"`.

### Shape
Phone container 26dp · cards/containers 18dp · pills/badges/buttons/nav/inputs 999dp (fully rounded) · icon chips perfect circles · totals strip 14dp · small icon-chip tiles 14dp.

### Spacing
8dp grid. Screen horizontal margins 18–22dp (20dp default, 24dp onboarding). Content top padding ~60–64dp below the status bar (use `WindowInsets.statusBars` + 24dp). List rows 44–52dp min height. Card padding 14–20dp. Grid/card gap 10dp; section gap 20–28dp.

### Motion
Calm, no bounce. Standard: 150ms ease for selection fills; 250–400ms ease-out for width/position changes (progress bar, snack-bar bite); toast slides up 250ms. Mascot idle "bob": translateY 0→−8dp, 3.2s ease-in-out infinite.

---

## Signature components (see "Component library" in `Mealsy Design System.html`)

**Status pill / snack bar** — 46dp tall, radius 999. Track `#DEE2C3`. Olive `#A6B565` block anchored right with width = remaining %. Left edge of the olive block has a "bite" made of three `#DEE2C3` circles (14/16/12dp) overlapping the edge. Olli (mascot video, 46dp) sits above the bite point, `translateX(-55%)`. Inside: left `1,340 kcal eaten` (500 14sp, oliveText), right state text (`560 left`).

**List row** — 48dp min, padding 9×16dp. 34dp pastel circle with 15dp stroked icon → label (400 14sp, flex 1) → ink count badge (`#1C1B17` bg, `#F6F1E1` text, 500 12sp, padding 2×9dp, radius 999) or muted "not yet" → 13dp chevron `#8B887C`. Divider 1dp `#DDD5BC` inset 16dp. Pressed bg `#E2DBC4`.

**Coach note** — surface card, padding 14×16dp, radius 18. 15dp olive 4-point sparkle icon + body text ≤2 sentences.

**Metric card** — surface, radius 18, padding 13×14dp. Label 400 12sp muted; value 500 19sp tabular.

**Progress ring** — olive stroke on `#DEE2C3` track.

**Buttons** — height ~50dp, radius 999, 500 15sp. Primary: ink bg / cream text, pressed `#3A3830`. Secondary: transparent, 1dp `#C9C2A9` border, ink text, pressed bg `#EBE5D0`. Destructive: `#BE7250` bg / `#3F2012` text; outlined variant border+text `#A85B3B`. Disabled: opacity 0.35.

**Bottom nav + FAB** — ink pill (`#1C1B17`, radius 999, padding 15×30dp) floating 26dp above bottom, 16dp side margins. Four 22dp stroked icons (active `#F6F1E1`, inactive `#8B887C`): home, meals (bowl), trends (line chart), chat. Centered 56dp olive FAB with 24dp `#2A3013` plus icon, shadow `0 4 14 rgba(28,27,23,.28)`, pressed scale 0.94.

**Meal card** — image 18dp radius, title display, pastel metadata tags (`412 kcal` butter, `28g protein` leaf, `USDA verified` powder).

**Chat bubbles** — max width 82%, padding 11×14dp, 400 14sp/1.5. Coach: `#EBE5D0`, radius `18 18 18 6`, align start. User: `#DCE3BE` text `#2A3013`, radius `18 18 6 18`, align end. Typing indicator: three 6dp `#8B887C` dots at opacity 1/.7/.4.

**Input** — pill, 1dp `#C9C2A9` border, padding 15×20dp, 400 15sp; focus border 1.5dp ink. Chat variant has a mic icon trailing.

**Toggle** — on = olive track. **Toast** — ink pill, olive check icon, 500 13sp cream text, positioned above nav.

**Segmented control** — cream `#F6F1E1` track, 1dp `#C9C2A9` border, radius 999, 3dp padding; segments equal-width, 500 13sp; selected = ink bg + cream text, unselected = transparent + muted text. 150ms bg transition.

**Stepper** — same track styling; 28dp round −/+ buttons (pressed `#E2DBC4`), center value 500 13sp tabular min-width 44dp.

**Tag chip (tiny)** — pastel bg, 10sp 500, padding 2×8dp, radius 999, tracking 0.04em.

**Mascot (Olli)** — `assets/mascot.webm` (transparent, loop, muted). Ship as WebM (VP9 with alpha) via Media3, or export to Lottie/animated WebP. Allowed ONLY on: onboarding, empty states, chat header, snack-bar bite. Never elsewhere on data screens.

---

## Screens

### 1. Onboarding flow (`Mealsy Onboarding.html`) — 6 states
Canvas cream. Persist step state across process death.

**Step 0 · Welcome** — 4 decorative 6–8dp pastel dots at fixed offsets (butter 36,88 · pink right 52,120 · powder right 30,270 · leaf 28,330). Padding 64×24dp. H1 `EAT WELL / WITH A / COACH WHO / LISTENS` (46sp 600 uppercase, tracking −0.02). Olive squiggle underline (120×12dp SVG path, stroke 3). Mascot 200dp centered bottom with bob animation; speech bubble `HI, I'M OLLI` (surface, radius `16 16 16 4`, 500 12sp tracking 0.06em) top-right of mascot. Pill outline label `IT'S EASIER TOGETHER` (500 11sp tracking 0.1em muted). Buttons: primary `Get started`, secondary `I already have an account`. Bottom padding 28dp.

**Steps 1–4 shared chrome** — padding 60×24×28dp. Top row: 38dp circular back button (1dp hairline border, 15dp chevron), 6dp progress bar (`#DEE2C3` track, olive fill = step/4, 350ms), `N of 4` (500 12sp muted). Bottom: full-width primary button, label `Continue` (`Finish` on step 4; `Nothing to avoid` on step 3 when no chips selected). Disabled (opacity .35) when step 1 name empty or step 2 no goal.

**Step 1 · Name** — H1 `What should I call you?` (30sp 500), sub `Just a first name is fine.` Pill input placeholder `Your name`.

**Step 2 · Goal** — H1 `What are you here for, {firstName}?` Sub `I'll shape my advice around this. You can change it anytime.` Four selectable cards (surface, radius 18, padding 14×16dp, 1.5dp border transparent→ink when selected, check icon trailing when selected). 34dp pastel circle with initial letter:
- butter — `Lose weight steadily` / `A gentle deficit, no crash targets` → target 1800
- leaf — `Maintain where I am` / `Keep energy and habits consistent` → 2200
- powder — `Build muscle` / `More protein, a small surplus` → 2600
- pink — `Just understand my eating` / `No targets, only awareness` → 2200 (maps to backend `tracking_mode: "mindful"`)

**Step 3 · Preferences** — H1 `Anything you avoid?` Sub `Pick all that apply — I won't suggest meals that clash.` Multi-select chips (radius 999, padding 10×17dp, 500 13sp; off = transparent + hairline border; on = ink bg + cream text): Vegetarian, Vegan, Pescatarian, No dairy, No gluten, Low sodium, Low sugar, No nuts.

**Step 4 · Target** — H1 `Your daily target`. Sub = goal-specific "why" copy (see HTML `goals[].why`). Surface card: label `Daily calorie goal` + value `2,000 kcal` (500 26sp tabular); slider 1400–3200 step 50 (track 6dp `#DDD5BC`, fill olive, thumb 24dp cream with 2dp ink border); min/max labels 11sp `#8B887C`. Coach note below with dynamic line (`Noted — I'll steer around {prefs} when suggesting meals.` or `I'll suggest a mix of whole foods and keep portions realistic.`).

**Step 5 · Done** — centered: mascot 150dp bobbing, H1 `Ready when you are, {firstName}`, sub `Tell me what you eat in plain words. I'll handle the numbers.`, olive pill summary `{Goal} · 2,000 kcal / day`. Then navigate to Home.

API: on finish → `POST /goals` `{kcal_goal, protein_goal, fiber_goal, dietary_prefs, tracking_mode}` (see `goals.py` / `GoalData` type).

### 2. Home / Dashboard (`Mealsy Design System.html` → "Example screens → HOME")
Scrollable, padding 64×20dp, bottom padding 120dp for nav. Eyebrow date `WEDNESDAY, AUG 6`. Display greeting (32sp 500, max width 260dp), e.g. `Good afternoon, Sam`. Snack-bar status pill at 44dp top margin (the ONE olive element). Three metric cards in a 3-col grid, gap 10dp: Protein `86g`, Carbs `152g`, Fat `48g`. Section `Today's meals` (17sp, margin 28 top / 12 bottom). Surface list container with rows: Breakfast (butter, count 2), Lunch (leaf, 1), Dinner (pink, `not yet`), Snacks (powder, 1). Coach note (`You're 24g short on protein today. Greek yogurt this afternoon would close the gap.`). Bottom nav + FAB overlay. FAB tap → quick-log (chat with meal-logging intent); mock shows ink toast `Quick log opened`.

API: `GET /meals/today` → `TodayTotals {kcal, protein_g, fiber_g, n_meals, by_type[]}`; `GET /goals` for targets. Snack bar: eaten % = kcal / kcal_goal.

### 3. Meal detail (`Mealsy Design System.html` → "MEAL DETAIL")
Padding 60×20×32dp. Header row: 38dp circular back, centered eyebrow `LUNCH · 12:40`, 38dp spacer. Hero image 210dp tall, radius 18 (`assets/meatballs.jpg` placeholder). Title 28sp 500. Tag row (gap 6dp): `412 kcal` butter, `28g protein` leaf, `USDA verified` powder (padding 4×11dp, 500 12sp). Olive status pill: `Fits today's budget` / `560 kcal remaining` (the ONE olive element). Section `What's in it` → surface list; rows = ingredient name (flex) + `120g · 254 kcal` (13sp muted tabular), 48dp min, padding 12×16dp. Coach note. Buttons: primary `Log this meal`, secondary `Edit portions`.

API: items from `LogMealResponse.items[]` / `MyMealDetail.ingredients[]`; `estimated=false` + `source="USDA"` → show "USDA verified" tag.

### 4. Coach chat (`Mealsy Design System.html` → "AI COACH CHAT")
Header padding 60×20×14dp, 1dp divider bottom: mascot 34dp + `Coach` (500 16sp) / `answers in about 15 seconds` (12sp muted). Message list padding 18×16dp gap 8dp. Coach bubbles may contain a row of pastel metadata tags (e.g. `412 kcal`, `28g protein`). Typing indicator while awaiting reply. Bottom: pill input with mic icon + send.

API: `POST /meals/log` `{user_input, conversation_id, image_b64?, meal_type?, action?}` → `LogMealResponse {status, message, paused, items[], meal_id?}`. When `paused=true` and `items.length>0`, render the **Meal confirm card** (screen 5) inline as a coach message.

### 5. Meal confirm card (`Meal Confirm Card.html`) — inline in chat
Coach bubble `Here is what I found — confirm, edit, or cancel.` with 34dp mascot. Then surface card (radius 18, padding 20dp, gap 16dp):
1. Header: eyebrow `CONFIRM MEAL` + `3 items` (12sp muted, right).
2. `Log this as` label (12sp muted) + segmented control: Breakfast · Lunch · Dinner · Snack (`brunch` exists in the API; omit from UI or add if the user's first-meal time suggests it).
3. Food rows (padding 14×0, divider 1dp `#DDD5BC`):
   - 32dp pastel icon circle (leaf for protein, butter for fats/dressings, powder for estimated) with 15dp stroked icon
   - Humanized name (500 14sp) — derive from USDA `food_name` (e.g. `Chicken, broiler or fryers, breast, skinless, boneless, meat only, cooked, grilled` → `Grilled chicken breast`); show the raw USDA string below in 12sp muted
   - Meta `181 kcal · 37g protein` (12sp muted tabular) + powder tag `estimated` when `item.estimated`
   - `×` remove (16sp muted, hover/press `#A85B3B`) top-right
   - Second line (indented 42dp): underlined link `Not the right food?` (opens `candidates[]` picker) left; gram stepper right (±5 g, min 5)
4. Totals strip (`#DEE2C3`, radius 14, padding 14×16dp, 5 equal columns): label 10sp uppercase tracking 0.1em `#4B5227`; value 700 19sp `#2A3013` tabular. kcal · Protein · Carbs · Fat · Fiber. Zero values at opacity 0.45.
5. Portion row: `Portion` label + segmented `0.5× 1× 1.5× 2×`.
6. Actions: secondary `Cancel` (fixed width) + primary `Confirm & log` (flex 1).
7. Optional (behind divider): pill input `Name for My Meals…` + secondary `Add to My Meals`.
Timestamp `07:39 PM` (11sp `#8B887C`) right-aligned below card.

Totals recompute live: `Σ(per_gram × grams) × portion`.

API: Confirm → `POST /meals/log-items` `{meal_type, portion, items: LogItemInput[]}` where `target_qty_g` = edited grams. Add to My Meals → `POST /my-meals` `{name, ingredients}`.

### 6. Landing page (`Mealsy Landing Page.html`)
Marketing web page, not part of the Android app. Included for brand reference only (hero copy, voice, integrations list).

---

## Interactions & state summary
- Onboarding: `step (0–5)`, `name`, `goal`, `prefs[]`, `kcalTarget`; back preserves entries.
- Home: `today` totals, `goals`, `meals by type`; pull-to-refresh.
- Chat: `messages[]`, `conversationId`, `isTyping`, pending `confirmCard` (items, mealType, portion, grams overrides).
- Confirm card: local edits until Confirm; Cancel discards and sends `action: "cancel"`.
- Bottom nav: 4 destinations (Home, Meals, Trends, Chat) + FAB. Trends and Settings screens are **not yet designed** — use the token/component library and match density of Home.
- Auth: Supabase (see `frontend/src/lib/supabase.ts`, `authStore.ts`); bearer JWT on every request.

## Voice (copy rules)
Short, specific, second person. Explain why, suggest one concrete action, never scold. No exclamation marks, no streak pressure, no diagnoses. Sentence case for labels; uppercase only for eyebrows and the welcome headline.

## Assets
- `assets/mascot.webm` — Olli, transparent looping animation (from nutrichat frontend mascot component)
- `assets/meatballs.jpg` — placeholder meal photo (from `nutrichat/data`)
- Icons: 24-grid stroked line icons, 1.8–2dp stroke, round caps. Paths are inline in the HTML; recreate as `ImageVector`s or use Lucide-style equivalents.
- Font: Geist — https://fonts.google.com/specimen/Geist

## Files in this bundle
- `Mealsy Design System.html` — tokens (light + dark), full component library with states, and four phone screens (Onboarding welcome, Home, Meal detail, Coach chat). **Start here.**
- `Mealsy Onboarding.html` — interactive 6-state onboarding flow.
- `Meal Confirm Card.html` — interactive confirm card (steppers, tabs, portion, remove).
- `Meal Type Selector Options.html` — three explored variants for the meal-type selector; variant 1b (segmented) was chosen.
- `Mealsy Landing Page.html` — web marketing page, brand reference only.
- `DESIGN_SYSTEM_SPEC.md` — the condensed design-system spec (drop into the Android repo as CLAUDE.md so Claude Code follows it).
- `assets/` — mascot + placeholder photo.

Backend reference (in the nutrichat repo): `src/backend/api/{meals,goals,my_meals,mindful,nutrient_checkup,quota}.py`, `frontend/src/api/types.ts` for response shapes.
