# Mealsy design system — "warm clinical"

All new components and pages in this project MUST follow this system. Reference implementation: `Mealsy Design System.dc.html` (tokens, component library, example screens). Styling is always inline (DC rules) — copy literal values from here.

## Colors (light)
- Cream canvas `#F6F1E1` — page background everywhere
- Beige surface `#EBE5D0` — cards, list containers, coach notes; pressed `#E2DBC4`
- Divider `#DDD5BC` — hairlines inside beige
- Ink `#1C1B17` — display type, count badges, nav bar; pressed `#3A3830`
- Olive hero `#A6B565` (text on it `#2A3013`; pale track `#DEE2C3`) — exactly ONE full-width status element per screen; no status → no olive
- Pastel chips (32–36px icon circles + tiny metadata tags ONLY, never fills/backgrounds/buttons): butter `#F2D45C`/text `#4A3A08`, pink `#F0A9C6`/`#5A1F3A`, leaf `#A9C46F`/`#2A3013`, powder `#A9C0E4`/`#1E3050`
- FAB: olive `#A6B565`, icon `#2A3013` — the black nav + olive FAB is the single high-contrast focal point; pink `#F0A9C6` is pastel-chip use only
- Muted text `#6F6A58`; inactive nav `#8B887C`; hairline borders `#C9C2A9`
- Destructive: muted terracotta `#BE7250` (text `#3F2012`), outline variant text `#A85B3B`, never red
- Text on any colored fill = much darker same hue, never black/gray. No gradients, no shadows (except FAB `0 4px 14px rgba(28,27,23,0.28)`), no pure white/black. Screens ~90% cream/beige/ink.

## Colors (dark)
Canvas `#201F1A`, surface `#2B2A23`, divider `#3A382E`, ink flips to cream `#F6F1E1`, muted `#A8A493`, inactive `#7A776B`. Pastels dimmed: `#D9BE53` `#D898B2` `#98B064` `#98ACCD`; olive `#96A45B` (text `#1E230D`). Nav stays ink + hairline `#3A382E` border; FAB stays olive `#A6B565`.

## Type
Fonts: `https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700;800&display=swap`
- Display: Geist 28–34px medium, letter-spacing −2%, may break two lines
- Section header: Geist 17–18px medium · Body: 14px/1.5 regular · Label: 12–13px `#6F6A58` sentence case
- Eyebrow: 11px, letter-spacing 0.12em, uppercase, `#6F6A58`
- Numbers: tabular figures (`font-variant-numeric:tabular-nums`), medium, Geist for big values

## Shape & spacing
8px grid; screen margins 18–22px; list rows 44–52px min-height. Radii: 26px phone container, 18px cards/containers, 999px pills/badges/nav/buttons, perfect circles for icon chips.

## Signature components (see reference file for exact markup)
Status pill (snack-bar variant: pale-olive track = eaten, olive remainder with bite-notch edge, mascot video at the bite point) · list row (pastel circle + label + ink count badge + chevron, hairline dividers) · coach note (olive sparkle + ≤2 sentences) · metric card · progress ring (olive on `#DEE2C3`) · black pill nav + pink FAB · buttons (ink primary / hairline secondary / terracotta destructive) · meal card · chat bubbles (beige coach `18px 18px 18px 6px`, olive-tint user `#DCE3BE` text `#2A3013` `18px 18px 6px 18px`) · pill input with mic · toggle (on = olive) · ink toast with olive check.

## Mascot
Olli = `assets/mascot.webm` (autoplay loop muted). Onboarding, empty states, coach header, status-bar bite only — never on data screens otherwise.

## Voice
Short, specific, second person. Explain why, suggest one concrete action, never scold. No exclamation marks, no streak pressure, no diagnoses.

## Screens
Phone content needs ~60–64px top padding to clear the IOSDevice status bar. Frames: `<x-import component-from-global-scope="IOSDevice" from="./ios-frame.jsx" hint-size="400,860">`.
