# Feature Specification: Sugar & Micronutrient Analytics

**Feature Branch**: `004-micronutrient-analytics`

**Created**: 2026-09-28

**Status**: Draft

**Input**: User description: "I want to add analytics showing sugar intake and other micronutrients"

## Context

Mealsy already gives users two related views:

- **Nutrient Check-up card**: a rolling 7-day daily average for Protein, Fiber,
  Sugar, Vitamin C, Vitamin D, Iron, Calcium and Vitamin B-12, with a trend arrow
  compared with the prior week and a percent-of-daily-value figure. It is rebuilt
  once a night.
- **Trends section**: day-by-day calorie and meal history (heatmap/sparkline).

Neither view lets a user see how sugar or a micronutrient changes **day by day**
over a period they choose, which foods drive it, or how complete the underlying
data is. This feature adds that analytics view. It builds on the Check-up
instead of replacing it.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See my sugar intake over time (Priority: P1)

A user who wants to cut back on sugar opens the analytics view and sees their daily
sugar intake for the last 7 days as a chart. The chart has a reference line at the
daily sugar limit, the period average, and how many days they were over the limit.
They can switch the period to 30 or 90 days.

**Why this priority**: Sugar is the nutrient the user named, and it is the one
people most often try to limit. A per-day view with a limit line answers "how am I
doing?" in a way the 7-day average cannot.

**Independent Test**: Seed a user with meals across 10 days, some containing sugary
foods. Open the analytics view and confirm that each day's sugar total matches the
sum of that day's logged items, that the limit line is shown, and that the
"days over limit" count is correct.

**Acceptance Scenarios**:

1. **Given** a user with meals logged on 5 of the last 7 days, **When** they open
   sugar analytics with the 7-day range, **Then** they see 7 days on the chart.
   The 5 logged days show their sugar totals and the 2 unlogged days are marked
   "no data" rather than shown as zero.
2. **Given** a day whose sugar total is above the daily sugar limit, **When** the
   chart is shown, **Then** that day is visually marked as over the limit and counts
   toward "days over limit".
3. **Given** the user switches the range from 7 to 30 days, **When** the view
   refreshes, **Then** the chart, the average and the over-limit count all reflect
   the 30-day period.
4. **Given** the user logs a sugary snack today, **When** they return to the
   analytics view, **Then** today's sugar total includes that snack without
   waiting for a nightly update.

---

### User Story 2 - Explore other micronutrients (Priority: P2)

The user picks another nutrient from a list, such as Iron, Calcium, Vitamin C,
Vitamin D, Vitamin B-12, Fiber or Sodium. They see the same daily chart against
that nutrient's daily target, so they can spot nutrients they are consistently
low on.

**Why this priority**: This extends the P1 view to the "other micronutrients"
the user asked for. It reuses the same interaction, so the extra value is high
for little new UX.

**Independent Test**: Choose Iron for a seeded user and confirm the daily totals
and the percent-of-target figures match the logged foods.

**Acceptance Scenarios**:

1. **Given** the analytics view is open, **When** the user selects Iron, **Then**
   the chart shows daily iron totals against the iron daily target, with the
   period average shown as a percent of target.
2. **Given** a nutrient to limit (Sugar, Sodium) versus a nutrient to reach (Iron,
   Fiber), **When** each is shown, **Then** the view frames it correctly. For a
   nutrient to limit, it counts days over the limit. For a nutrient to reach, it
   counts days under the target.
3. **Given** the user opens the list of nutrients, **When** they view it, **Then**
   each nutrient shows its period average as a percent of target, so the user can
   see at a glance which ones are low or high.

---

### User Story 3 - Know which foods drive a nutrient (Priority: P2)

For the nutrient and period they have selected, the user sees the top foods that
contributed most, for example "Orange juice: 38% of your sugar this week". They
can then act on specific foods rather than on an abstract number.

> **Data source (spec 008):** every logged food stores its own tracked
> micronutrients, and `GET /nutrients/daily?meals=true` lists each meal's
> `foods` with their values.

**Why this priority**: Knowing which foods drive a number is what turns it into a
change in behaviour. It ranks just below Story 2 because the charts are useful
on their own.

**Independent Test**: For a seeded week in which one food supplies most of the
sugar, confirm that food is ranked first and that its share matches its
contribution.

**Acceptance Scenarios**:

1. **Given** a period with logged foods containing sugar, **When** the user views
   sugar analytics, **Then** they see up to 5 top contributing foods, each with its
   amount and its share of the period total.
2. **Given** the same food was logged on several days, **When** contributors are
   ranked, **Then** that food's contributions are combined into one entry.

---

### User Story 4 - Trust the numbers (Priority: P3)

Some logged foods have only estimated calories and macros, with no vitamin or
mineral data. The analytics view tells the user how complete the data is for the
selected nutrient, so a low iron number caused by missing data is not mistaken
for a real deficiency.

**Why this priority**: This protects users from acting on misleading low numbers.
It is lower priority because P1 and P2 still work without it, just with less
context.

**Independent Test**: Seed a week in which half the items are estimated with no
micronutrient data. Confirm the view shows reduced completeness for Vitamin C and
full completeness for calories.

**Acceptance Scenarios**:

1. **Given** that some logged items in the period have no data for the selected
   nutrient, **When** the view is shown, **Then** the view says how complete the
   data is, for example "Based on 12 of 18 logged items".
2. **Given** that completeness for the period is below 50%, **When** the view is
   shown, **Then** it shows a clear note that the numbers may undercount, and it
   does not label the period as "low".

---

### Edge Cases

- **New user or empty period**: If nothing is logged in the selected range, the
  view shows an empty state that prompts the user to log meals. It does not show
  a flat line at zero.
- **Unlogged days inside a period**: These days are excluded from averages and
  shown as "no data". They are not treated as zero intake.
- **Edited or deleted meals**: When a user edits or deletes a meal, the analytics
  reflect the change the next time the view is opened.
- **Nutrient day boundary**: Daily totals use the same "nutrition day" boundary as
  the rest of the app, which has a configured reset hour and timezone, so a
  late-night snack lands on the same day it does in the daily totals.
- **Extreme single entries**: If one mis-logged item, such as 2 kg of sugar,
  distorts the chart, the day still shows. The value is not hidden, and the
  scale stays readable (for example, the axis is capped and the capped bar is
  labelled).
- **Nutrient without a target**: If a nutrient has no daily target, the chart
  shows the amounts with no reference line and no percent-of-target.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to open a nutrient analytics view from
  [NEEDS CLARIFICATION: which surfaces ship in v1: web dashboard only, the
  Android app only, or both? Also, should the chat assistant answer questions
  such as "how much sugar did I have this week?" from the same data?].
- **FR-002**: The system MUST show daily totals for the selected nutrient across
  a selected period. The periods offered are 7, 30 and 90 days, and the default
  is 7.
- **FR-003**: The system MUST offer at least Sugar, Sodium, Fiber, Iron, Calcium,
  Vitamin C, Vitamin D and Vitamin B-12. Sugar is selected by default.
- **FR-004**: The system MUST show each nutrient's daily reference value as a line
  on the chart. It MUST also say whether that value is a limit to stay under
  (Sugar, Sodium) or a target to reach (all the others).
- **FR-005**: The system MUST show, for the selected period, the average daily
  amount, the average as a percent of the reference value, and the count of days
  over the limit or under the target.
- **FR-006**: The system MUST exclude days with no logged meals from averages and
  day counts, and MUST show those days as "no data".
- **FR-007**: The system MUST show up to 5 foods that contributed most to the
  selected nutrient in the period. Each food MUST show its amount and its percent
  share, and repeated foods MUST be combined into one entry.
- **FR-008**: The system MUST show data completeness for the selected nutrient and
  period, meaning the share of logged items that carry a value for that nutrient.
  When completeness is below 50%, it MUST show an undercount warning.
- **FR-009**: The analytics MUST include meals logged today. A newly logged,
  edited or deleted meal MUST be reflected the next time the view is opened.
- **FR-010**: The system MUST show each user only their own data.
- **FR-011**: The system MUST use the same daily reference values as the existing
  Nutrient Check-up, so the two views never disagree about a nutrient's target.
  The daily sugar limit MUST be [NEEDS CLARIFICATION: should it stay the generic
  50 g for everyone, or can users set their own sugar limit? A personal limit
  matters for users with a diabetes or prediabetes condition on their profile.]
- **FR-012**: Every chart value MUST also be available as text or through
  accessible labels, so the view can be used with a screen reader.

### Key Entities *(include if feature involves data)*

- **Tracked Nutrient**: A nutrient offered in analytics. It has a display name,
  a unit, a daily reference value, and a direction: a *limit* to stay under or a
  *target* to reach.
- **Daily Nutrient Total**: One user's total of one nutrient for one nutrition
  day. Days with no logged meals are marked "no data".
- **Period Summary**: The figures for the selected nutrient and period: the
  average, the percent of the reference value, the count of days over the limit
  or under the target, and the data completeness.
- **Food Contribution**: A food's combined amount of the selected nutrient in the
  period, and its share of the total.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can go from the main screen to their 7-day sugar chart in 2
  taps or fewer.
- **SC-002**: The analytics view loads in under 2 seconds for a 90-day range at the
  95th percentile.
- **SC-003**: Every daily total shown matches the sum of that day's logged items
  to within 1% (tested on a seeded dataset of at least 30 days).
- **SC-004**: Among users who log meals on at least 3 days, 30% or more open the
  analytics view within their first 14 days after launch.
- **SC-005**: In a usability check, 4 out of 5 test users can correctly say which
  food contributed most to their sugar last week, using only the analytics view.
- **SC-006**: No period whose data completeness is below 50% is shown to the user
  as "low" without the undercount warning.

## Assumptions

- The nutrient data comes from what is already stored with each logged meal.
  Foods matched to USDA carry full micronutrient data. Foods whose nutrients were
  estimated carry only calories and macros, and FR-008 covers this gap.
- Daily reference values are the generic adult values the Check-up already uses.
  Sodium, which the Check-up does not yet track, uses the FDA daily value of
  2,300 mg. The values are not personalised by age, sex or pregnancy in v1.
- Sugar means **total sugars** as reported by USDA. Added sugars are out of
  scope, because the food data does not reliably separate them.
- The existing Nutrient Check-up card stays. It may link to the analytics view,
  but its nightly behaviour does not change.
- Exporting data, sharing, and comparing with other users are out of scope.
- Medical advice is out of scope. The view reports intake against general
  reference values and does not diagnose deficiencies.
