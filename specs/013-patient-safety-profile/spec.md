# Feature Specification: Patient Safety Profile and Constraint-Checked Meals

**Feature Branch**: `user_memory` (spec directory `013-patient-safety-profile`)

**Created**: 2026-11-10

**Status**: Draft, open questions resolved 2026-11-12 (see Decisions)

**Input**: User description: "The agent must remember each patient's
preferences, conditions, and limitations across sessions, and must never show
a meal that violates a hard constraint. Safety-critical facts must not depend
on retrieval." Followed by six build phases (structured profile, deterministic
constraint checker, red-flag screening, memory write path, soft memory and
meal history, dietitian review), agent behaviour requirements, evals,
non-goals, constraints and acceptance criteria (reproduced in the Phases
section).

## Background: what exists today

Mealsy already remembers things about a user, but not in the shape this
feature needs.

- **Preference memory** (feature #61, dark-launched, off for every user in
  production): a small, typed profile of facts (restriction, dislike, like,
  habit, context) with a source (stated by the user, inferred from chat,
  inferred from logs). It is rendered in full into every coaching prompt when
  enabled, so it already does not depend on retrieval. Writes go through one
  rule set: background curators may tighten but never loosen, only the user
  can remove a restriction, and removed facts are remembered so they are not
  learned again. However, edits rewrite a fact in place, so history is lost;
  and the curator is told to never store diagnoses, medications or lab
  values.
- **Declared health conditions** (diabetes, prediabetes, hypertension,
  chronic kidney disease) and **diet settings** (vegan, gluten free, no nuts
  and so on) live on the user's goals, set from the app's settings. They have
  no date, source or history. Since fix #70 they reach the coach on every
  turn, and a coaching turn fails rather than answer when they cannot be
  loaded.
- **Meal suggestions are prose.** The coach answers questions, suggests
  snacks and dinners, and can draft a simple day plan, all as free text
  governed by prompt rules ("never suggest a restricted food"). Nothing in
  code checks a suggestion before the user sees it. Compliance is measured
  by an eval, not enforced.
- **Nutrition values** for logged meals come from the app's food database
  (bundled USDA FoodData Central), with a model estimate as the last
  fallback, and estimates are flagged as such.
- **Nobody but the user** has an account. There is no clinician, dietitian or
  staff role, no review surface, and no staff notification channel (the
  Telegram bot is discontinued). The web app is frozen; Android is the only
  surface under development.
- **Related drafts**: spec 012 (weekly meal plans) relies on prompt rules for
  restrictions and conditions; spec 010 (stateful chat) found that meal
  logging does not read restrictions at all. This spec provides the
  enforcement mechanism both of them lack.

This spec extends preference memory into a clinical-grade profile rather
than adding a second memory. One store holds every fact about the patient;
hard facts gain history, provenance and a confirmation step; a deterministic
checker stands between the model and the patient.

## Vocabulary

- **Patient**: a Mealsy user. Every user has a profile; there is no
  enrolment step.
- **Clinician**: a placeholder role. No dietitian or staff member has
  access today. The profile keeps "clinician" as a source and the review
  queue exists as a backend queue, so that a real clinician role can be
  added later without changing the data. Until then the team acts on the
  queue through a protected administrative interface (see Decisions).
- **Hard constraint**: an entry that a meal must never violate: a confirmed
  allergy, a diet setting, a clinician-set nutrient limit, a texture or
  physical limitation, or a drug-food interaction derived from a confirmed
  medication.
- **Soft preference**: likes, dislikes, cuisines, budget, cooking time, meal
  feedback. Shapes suggestions, never blocks them.
- **Pending / confirmed / retired**: the three states of a hard entry.
  Pending entries are known but not yet acted on. Only confirmed entries
  bind. Retired entries are kept for history and never bind again.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The patient's confirmed profile shapes every meal, every session (Priority: P1)

A patient with a peanut allergy, a sodium limit set by their dietitian and
trouble chewing opens the app a month after they first said so. They ask for
a dinner idea. The suggestion is soft-textured, low in sodium and peanut
free, and the coach says so: "Kept this soft and low-sodium because of your
chewing difficulty and your sodium limit." Nothing about their profile had to
be searched for; the whole confirmed profile is present whenever a meal is
suggested.

**Why this priority**: this is the promise of the feature. Without a
complete, typed, always-present profile nothing else can be checked.

**Independent Test**: create a profile with one entry of each type
(allergy, diagnosis, medication, physical limitation, nutrient limit), close
the session, start a new one, and ask for a meal. The suggestion respects
every confirmed entry and names the constraints it applied.

**Acceptance Scenarios**:

1. **Given** a patient with confirmed entries, **When** any recipe or meal
   plan is requested in a later session, **Then** every confirmed entry is
   available to the suggestion without any search or relevance ranking, and
   the reply names the constraints it applied.
2. **Given** a hard entry is changed (for example the sodium limit is
   lowered), **When** the profile is viewed afterwards, **Then** the old
   entry is shown as retired with its date and the new one as current, and
   nothing has been overwritten.
3. **Given** an entry that is pending (not yet confirmed), **When** a meal is
   suggested, **Then** that entry does not bind the suggestion, and the
   patient is reminded that it is awaiting confirmation.
4. **Given** the patient already had declared conditions, diet settings or
   stated restrictions before this feature, **When** the feature ships,
   **Then** those appear in the profile as confirmed, patient-sourced
   entries, and nothing they had set is lost.
5. **Given** the profile cannot be loaded, **When** a meal is requested,
   **Then** no meal is shown and the patient sees a clear "try again"
   message. The system never suggests a meal with an unknown profile.

---

### User Story 2 - No meal that breaks a hard constraint ever reaches the patient (Priority: P1)

The coach proposes a recipe. Before the patient sees it, plain code checks
every ingredient against the patient's allergens and drug-food interactions,
computes the recipe's nutrient totals from the food database and compares
them with the clinician's limits, and checks the texture and preparation
demands against the patient's physical limitations. A recipe that fails is
regenerated with the reason; after the maximum number of tries it is
dropped and the patient is told that no suitable meal could be found. Every
failure is logged with its reason.

**Why this priority**: it is the acceptance criterion with a target of
zero. Prompt rules alone measured at less than 100% in past evals.

**Independent Test**: run the eval set of synthetic patients. Zero
suggestions shown to a patient contain a confirmed allergen, exceed a
confirmed nutrient limit, break a texture or physical limitation, or
include a food that interacts with a confirmed medication.

**Acceptance Scenarios**:

1. **Given** a patient with a confirmed peanut allergy, **When** the model
   proposes a recipe containing peanut oil as a minor ingredient, **Then**
   the recipe is rejected before display, regenerated without peanut
   products, and the rejection is logged with "allergen: peanut".
2. **Given** a confirmed sodium limit per meal, **When** a proposed recipe's
   sodium computed from the food database exceeds it, **Then** the recipe is
   rejected even if the model's own estimate was within the limit.
3. **Given** a confirmed medication with a known food interaction (for
   example a blood thinner and high-vitamin-K foods, or a MAOI and aged
   cheese), **When** a recipe includes such a food, **Then** it is rejected
   with the interaction named.
4. **Given** a confirmed swallowing difficulty, **When** a recipe has a
   crunchy or dry texture, **Then** it is rejected on texture.
5. **Given** a confirmed limit on standing time or grip strength, **When** a
   recipe needs long active cooking time or heavy equipment, **Then** it is
   rejected on physical demand.
6. **Given** a recipe that fails the checker three times, **When** no
   compliant recipe is produced, **Then** the patient sees a short, warm
   message that no suitable meal could be found this time, with the option
   to try again or ask differently, and never a partial or unchecked recipe.
7. **Given** an ingredient the food database cannot resolve, **When** the
   recipe is checked, **Then** its nutrient contribution is treated as
   unknown: a recipe with an unknown contribution to a limited nutrient
   fails that limit check, rather than passing on a guess.
8. **Given** the allergen and interaction tables are edited by a clinician,
   **When** the next check runs, **Then** the new table content is used
   without a code change.

---

### User Story 3 - Dangerous messages get a fixed safe reply, not a model reply (Priority: P1)

A patient writes "I've stopped taking my insulin, what should I eat?" Before
any model sees the message, a rule-based screen written by the dietitians
matches it. The patient receives a fixed, safe response, the model is not
called, and the staff contact is notified with the message and the rule
that matched.

**Why this priority**: it is the cheapest protection against the worst
outcomes, and the owner asked for it to ship with phases 1 and 2.

**Independent Test**: send each phrase in the dietitians' list, and
paraphrases they marked as expected matches. Each gets the fixed response,
no model call is recorded, and a notification is sent. Send ordinary
messages: none is screened.

**Acceptance Scenarios**:

1. **Given** a message matching a red-flag rule, **When** it is received,
   **Then** the patient gets that rule's fixed response, no model is called
   for that message, and a notification goes to the configured staff
   contact within one minute, carrying the message, the rule and the
   patient identifier.
2. **Given** the red-flag list is updated in its file, **When** the next
   message arrives, **Then** the updated list is in force without a code
   change.
3. **Given** an ordinary message, **When** screened, **Then** it passes with
   no visible delay (under 50 ms added to the turn).
4. **Given** a screened message arrives while a meal card is waiting for
   confirmation, **When** it is handled, **Then** the fixed response is
   sent and the waiting card is left as it was.
5. **Given** the notification cannot be delivered, **When** the screen
   matches, **Then** the patient still gets the fixed response, and the
   failed notification is logged and retried.

---

### User Story 4 - What the patient says becomes memory the right way (Priority: P2)

Mid-conversation a patient mentions "oh, and I found out I'm allergic to
shellfish". The coach reads back what it understood: "I'll note that you're
allergic to shellfish. Is that right?" The patient says yes. From the very
next recipe, shellfish is excluded. Had they said "actually no, it's my
sister", nothing would be saved. The same conversation also revealed they
dislike coriander and cook for one; those are saved directly, with the date.

**Why this priority**: it is how the profile grows without a clinician
typing it in, and the acceptance criterion about mid-conversation allergies
depends on it. It can ship after phases 1 to 3 because clinicians can enter
confirmed facts directly until then.

**Independent Test**: scripted conversations in the eval set state hard
facts and soft preferences. Clearly stated hard facts that add a constraint
bind at once and are mentioned once; uncertain ones appear as pending until
confirmed and bind immediately after; soft preferences appear directly; facts
the patient denies are not saved. Inference precision and recall per band are
measured against hand-labelled synthetic conversations.

**Acceptance Scenarios**:

1. **Given** a patient states an allergy, diagnosis, medication or physical
   limitation, **When** the decision model scores it in the ask band, **Then**
   a pending entry is created, the coach reads it back in the same session
   and asks for confirmation.
1a. **Given** a patient clearly states a new allergy ("I'm allergic to
   shellfish"), **When** the score is in the accept band, **Then** the entry
   is saved confirmed with source "inferred", the coach says once that it was
   noted and how to correct it, and the next recipe excludes shellfish.
1b. **Given** an inferred entry, **When** the patient opens their profile,
   **Then** it is labelled "inferred" and can be confirmed, corrected or
   retired there.
2. **Given** a pending entry read back to the patient, **When** they
   confirm, **Then** the entry becomes confirmed (source: patient) and is
   enforced on the very next recipe in that same conversation.
3. **Given** a pending entry read back, **When** the patient corrects or
   denies it, **Then** the entry is retired without ever binding, and the
   corrected version, if any, is read back again.
4. **Given** a patient states a like, dislike, cuisine, budget, cooking-time
   or meal feedback, **When** the turn is processed, **Then** it is saved
   directly with its date, without a confirmation step.
5. **Given** a patient says a confirmed hard entry no longer applies ("the
   doctor took me off warfarin"), **When** the turn is processed, **Then**
   the existing entry is not changed; a pending retirement is read back for
   confirmation, and only then is the entry retired.
6. **Given** a pending entry that is never confirmed, **When** the patient
   returns in a later session, **Then** the coach asks once more before any
   meal is suggested, and the entry stays pending if there is still no
   answer.

---

### User Story 5 - The coach remembers tastes and meals, and the patient can see and fix what it knows (Priority: P2)

Three weeks in, the patient asks for "something for a bad day". The coach
knows they like dal, dislike coriander, cook for one, and had khichdi twice
this week already, so it offers a different low-effort option. The patient
opens "What Mealsy knows about me", sees every hard entry with its state and
history and every soft preference with its date, corrects the cooking-time
preference and deletes a dislike. The next suggestion reflects both changes.

**Why this priority**: variety and taste make the coach worth using daily,
and the patient's right to view, correct and delete is a privacy
requirement. It does not affect safety, so it follows the P1 stories.

**Independent Test**: seed soft preferences and three weeks of planned, eaten
and rejected meals. A request returns a suggestion that matches the relevant
preferences and does not repeat a main meal served in the last three weeks
more than the allowed number of times. Viewing, correcting and deleting
entries works from the app and takes effect on the next request.

**Acceptance Scenarios**:

1. **Given** soft preferences and meal history exist, **When** a meal is
   requested, **Then** the preferences relevant to the request and the last
   three weeks of planned, eaten and rejected meals inform the suggestion,
   and the reply notes which were used.
2. **Given** a meal was suggested and the patient rejected it, **When**
   history is viewed, **Then** the rejection is recorded with the date and
   the reason, if given.
3. **Given** the patient views their profile, **When** the screen loads,
   **Then** every hard entry shows value, type, date, source and state, with
   retired entries available in a history view, and every soft preference
   shows its date.
4. **Given** the patient corrects or deletes a soft preference, **When** the
   next meal is requested, **Then** the change is reflected, and a deleted
   preference is not re-learned unless the patient states it again.
5. **Given** the patient asks to delete a confirmed hard entry from the
   screen, **When** they confirm the deletion, **Then** the entry is retired
   (not erased) with the date, and the patient is told it will no longer be
   applied.
6. **Given** the soft-preference search is unavailable, **When** a meal is
   requested, **Then** the hard profile still binds and a meal is still
   suggested, with soft preferences omitted.

---

### User Story 6 - Dietitians review what the system is doing (Priority: P3)

A reviewer (today a team member through a protected administrative
interface; later a dietitian, once that role exists) opens the review queue.
It lists pending profile changes (including conflicting-rule flags),
red-flag escalations, and a sample of generated plans. For each item they
can approve, reject or edit, and their decision becomes a clinician-sourced
entry or a resolved escalation.

**Why this priority**: it closes the loop for reviewers, but the earlier
stories work without it (patients confirm their own facts; escalations go to
the staff contact). No review screen is built in this feature: the queue and
its actions are backend-only until a clinician role exists.

**Independent Test**: create a pending entry, trigger a red flag and
generate a plan; all three appear in the queue. Approving the entry makes
it confirmed with source clinician; rejecting it retires it; editing it
retires the original and adds the edited version.

**Acceptance Scenarios**:

1. **Given** items of all three kinds exist, **When** the queue is opened,
   **Then** they are listed newest first with patient, type, content and
   date, and can be filtered by kind.
2. **Given** a pending profile entry, **When** a clinician approves, rejects
   or edits it, **Then** the profile reflects the decision with source
   "clinician" and the item leaves the queue.
3. **Given** a conflict flagged between two conditions' rules, **When** a
   clinician resolves it by choosing the limit that applies, **Then** that
   decision is stored as a clinician-sourced entry and used from then on.
4. **Given** a red-flag escalation, **When** a clinician marks it handled,
   **Then** it leaves the queue and the decision is kept with the date.
5. **Given** a sampled plan, **When** a clinician rejects it with a comment,
   **Then** the comment is stored with the plan's record for the eval set.

---

### Edge Cases

- **Conflicting rules**: two confirmed conditions imply opposite rules (for
  example a high-protein target from one and a protein ceiling from kidney
  disease). The suggestion follows the stricter rule, says that the rules
  conflict, and the conflict is flagged for the dietitian. The coach never
  resolves it by itself.
- **Missing clinical value**: the patient has a diagnosis with no clinician
  limit set ("I have CKD" but no potassium limit). The coach does not invent
  a limit; it applies no numeric limit for that nutrient, says a limit has
  not been set, and suggests asking their dietitian. No condition-specific
  default stands in for a clinical value.
- **Impossible constraints**: the confirmed profile leaves no compliant
  recipe (for example several allergies, a liquid-only texture and a very
  low calorie ceiling). After the maximum tries, the patient is told plainly
  and the case is logged for the dietitian. Nothing is relaxed.
- **Patient asks for a food they are allergic to**: the request is declined
  with the reason and an alternative. A confirmed allergy is never
  overridden in chat; only retirement with confirmation changes it.
- **Patient claims a clinician changed a limit**: saved as pending with
  source "patient" and read back; a clinician-sourced entry can only be
  created by a clinician.
- **Red flag inside a longer message**: the whole message is screened; a
  match anywhere wins. The fixed response replaces the entire reply.
- **Red-flag list unreadable** (file missing or malformed): the system
  refuses to answer any message with a model reply until the list loads,
  and the error is logged loudly. Safety screening fails closed.
- **Food database down**: recipes cannot be checked, so none are shown; the
  patient sees a retry message. Ordinary questions that suggest no food
  still work.
- **Pending entry and waiting meal card at the same time**: the two
  confirmations are kept apart; a reply is applied to the one the coach
  asked about last, and the coach says which one it took it as.
- **Ingredient quantities missing from the model's recipe**: the recipe is
  rejected as malformed and regenerated; a recipe without quantities cannot
  be totalled.
- **Two devices, same patient**: the profile is one record; a confirmation
  on one device is visible on the other on its next request.

## Requirements *(mandatory)*

### Functional Requirements

**Profile store (Phase 1)**

- **FR-001**: The system MUST keep one profile per patient with typed hard
  entries of these types: allergy, diagnosis, medication, physical
  limitation (chewing, swallowing, grip, standing time), and clinician-set
  nutrient limit (at least sodium, potassium, protein, fluid and
  carbohydrate, each with an amount, a unit and a period such as per meal or
  per day).
- **FR-002**: Every hard entry MUST carry a value, the date it was added, a
  source (patient, clinician or inferred) and a state (pending, confirmed or
  retired).
- **FR-003**: Hard entries MUST never be overwritten or deleted. A change
  retires the old entry (with the retirement date and who retired it) and
  adds a new one. The full history MUST be viewable.
- **FR-004**: Only confirmed entries MAY bind a suggestion. Pending entries
  MUST be shown to the patient as awaiting confirmation and MUST NOT be
  applied.
- **FR-005**: The complete set of confirmed hard entries MUST be included
  with every recipe and meal-plan request, in full and without any
  relevance search, ranking or truncation. If the set is too long to
  include, the request fails rather than truncating.
- **FR-006**: Existing declared conditions, diet settings and stated
  restrictions MUST be carried into the profile as confirmed, patient-sourced
  entries when the feature ships. The profile MUST be the single source for
  these facts afterwards; no second copy is kept.
- **FR-007**: If the profile cannot be loaded, the system MUST NOT suggest
  any meal and MUST tell the patient to try again.

**Constraint checker (Phase 2)**

- **FR-008**: Every recipe or planned meal MUST be produced in a structured
  form with: ingredients with quantities, texture, preparation steps,
  preparation time, and equipment. A suggestion that lacks any of these is
  rejected as malformed.
- **FR-009**: Before any recipe or planned meal is shown, a deterministic
  check (no model involvement) MUST validate it against the confirmed
  profile for: allergens (including derived ingredients, for example peanut
  oil for a peanut allergy), drug-food interactions from confirmed
  medications, nutrient limits, texture against chewing and swallowing
  limitations, and preparation demands against grip and standing-time
  limitations.
- **FR-010**: Nutrient totals used by the check MUST be computed from the
  app's food database (USDA FoodData Central), never taken from the model.
  An ingredient the database cannot resolve MUST count as unknown, and an
  unknown contribution to a limited nutrient MUST fail that limit's check.
- **FR-011**: A recipe that fails MUST be regenerated with the failure
  reasons given to the generator, at most 3 times in total. If no compliant
  recipe results, nothing is shown and the patient is told that no suitable
  meal could be found this time.
- **FR-012**: Every check failure MUST be logged with the patient, the
  recipe, the rule that failed and the values compared.
- **FR-013**: Allergen groups (which ingredients belong to which allergen)
  and drug-food interaction tables MUST live in data files that a clinician
  can read and edit without a code change, and the check MUST use the
  current file content.
- **FR-014**: Diet settings (vegan, vegetarian, gluten free, dairy free, no
  nuts and the rest) MUST be treated as hard constraints by the check.

**Red-flag screening (Phase 3)**

- **FR-015**: Every incoming patient message MUST be screened against a
  rule list kept in a configuration file written by the dietitians, before
  any model call. Each rule carries its fixed safe response.
- **FR-016**: On a match the patient MUST receive the rule's fixed response,
  no model MUST be called for that message, an escalation record MUST be
  stored, and a notification MUST be sent to the configured staff contact
  (a configurable webhook address; see Decisions) with the message, the
  rule and the patient identifier.
- **FR-017**: If the rule list cannot be read, the system MUST NOT produce
  model replies until it can, and MUST log the failure.
- **FR-018**: Screening MUST add no more than 50 ms to a turn.

**Memory write path (Phase 4)**

- **FR-019**: After each conversation turn, the system MUST propose profile
  updates: hard facts (allergy, diagnosis, medication, physical limitation)
  and soft preferences (likes, dislikes, cuisine, budget, cooking time, meal
  feedback).
- **FR-020**: Each proposed hard fact MUST be scored by the decision model,
  and deterministic code MUST place it in one of three bands by that
  probability, using thresholds set from the inference eval:
  - **accept**: only when the fact adds a constraint (a new allergy,
    diagnosis, medication, physical limitation or a stricter nutrient
    limit). It is saved confirmed with source "inferred", binds from the next
    suggestion, and the coach mentions it once ("I've noted your shellfish
    allergy; tell me if that's wrong").
  - **ask**: saved pending and read back in the same session with a request
    for confirmation; it becomes confirmed only when the patient or a
    clinician confirms it.
  - **drop**: not saved.
  A fact that removes or loosens a constraint, and any fact the decision
  model could not score, MUST go to the ask band whatever its score.
- **FR-020a**: Patients MUST be able to add, edit and retire their own
  allergies, diagnoses, medications, physical limitations and nutrient
  limits from the app. Entries they add are confirmed with source
  "patient". Inferred entries are labelled "inferred" in the profile, and the
  patient can confirm, correct or retire them there.
- **FR-021**: A hard fact confirmed by the patient MUST be enforced on the
  very next recipe or plan in that conversation.
- **FR-022**: A proposed soft preference MUST be saved directly with its
  date. A soft preference the patient has deleted MUST NOT be re-learned
  unless they state it again.
- **FR-023**: The system MUST NOT infer a hard fact from logged meals or from
  anything the coach itself said. Only the patient's own statements may
  produce a pending hard fact.
- **FR-024**: A statement that a confirmed hard entry no longer applies MUST
  produce a pending retirement that is read back and confirmed before the
  entry is retired.

**Soft memory and meal history (Phase 5)**

- **FR-025**: The system MUST record every planned, eaten and rejected meal
  with its date, and a rejection reason when given.
- **FR-026**: For each recipe or plan request, the system MUST retrieve the
  soft preferences relevant to the request and the last 3 weeks of meal
  history, and use them for fit and variety.
- **FR-027**: Soft-preference retrieval MUST be an enrichment: if it fails
  or times out, the request still completes with the hard profile applied.
- **FR-028**: Patients MUST be able to view everything remembered about
  them (hard entries with state and history, soft preferences with dates,
  meal history), correct soft preferences, delete soft preferences, and
  request retirement of a confirmed hard entry (with a confirmation step).

**Dietitian review (Phase 6)**

- **FR-029**: Reviewers MUST have a queue of pending profile changes,
  flagged rule conflicts, red-flag escalations and a sample of generated
  plans, each with approve, reject and edit actions, reachable through a
  protected administrative interface. No review screen is built until a
  clinician role exists.
- **FR-030**: A clinician's decision MUST be stored as a clinician-sourced
  profile entry (or a resolved escalation) with the clinician and date.
- **FR-031**: Only an action taken through the reviewer interface MAY
  create an entry with source "clinician". Patients cannot.

**Agent behaviour**

- **FR-032**: Every suggestion MUST state which constraints it applied and
  why, in one plain sentence ("kept low-sodium and soft texture because of
  your sodium limit and chewing difficulty").
- **FR-033**: When a value the suggestion needs is missing (for example a
  limit for a declared condition), the coach MUST say so and ask or defer.
  It MUST NOT guess a clinical value or apply a default in its place.
- **FR-034**: The coach MUST NOT diagnose, suggest changing a medication, or
  set a clinical target. Such requests get a decline and a pointer to the
  patient's clinician.
- **FR-035**: When two conditions' rules conflict, the suggestion MUST
  follow the stricter rule, say that the rules conflict, and flag the
  conflict for the dietitian.
- **FR-036**: The coach MUST offer swaps and low-effort options when asked
  for an easier choice or on a stated bad day. Tone is warm, plain and
  non-judgemental.
- **FR-037**: A confirmed allergy MUST NOT be overridden by a request in
  chat; the request is declined with an alternative.

**Logging, privacy and performance**

- **FR-038**: Every recommendation shown MUST be logged with the profile
  version it was checked against and the check result.
- **FR-039**: Patient profile data MUST be encrypted at rest.
- **FR-040**: Patient data (messages, profile content, meal history) MAY be
  sent only to the approved services: the database host, the application
  host, the LLM provider, the observability service and the typed-judgment
  service (Fastino GLiDE). The typed-judgment service MAY receive message
  text, candidate facts and reply text for routing, fact inference and reply
  checks; it MUST NOT receive the patient's name, email or full profile.
- **FR-040a**: The push provider MAY receive only device tokens and
  notification text that contains no profile content.
- **FR-040b**: Deleting an account MUST erase the patient's profile, soft
  preferences, meal history, recommendation records and escalations
  (GDPR right to erasure). Patients MUST be able to obtain a copy of
  everything remembered about them (FR-028 covers viewing).
- **FR-040c**: Logged failures, traces and escalation notifications MUST
  identify the patient by identifier, never by name or email.
- **FR-041**: Turns that do not request a recipe or plan MUST be no slower
  than today. Recipe and plan requests MAY take longer, within a stated
  budget set at planning.

**Evals (built with Phases 1 and 2, run in CI)**

- **FR-042**: An eval set of 20 to 30 synthetic patients with scripted
  multi-session conversations and hand-labelled expected profiles MUST exist
  before Phase 2 merges, and MUST run in continuous integration.
- **FR-043**: The eval MUST report: hard-constraint violation rate,
  extraction precision and recall, recall of facts from earlier sessions,
  handling of updated facts, abstention when information is missing,
  nutrient-total error against the food database, and tokens and latency per
  plan.

### Key Entities

- **Profile entry (hard)**: one fact about a patient. Type (allergy,
  diagnosis, medication, physical limitation, nutrient limit), value (for
  limits: nutrient, amount, unit, period), date added, source (patient,
  clinician, inferred), state (pending, confirmed, retired), retirement date
  and actor, and the entry it replaced, if any. The ordered set of confirmed
  entries at a point in time is the **profile version**.
- **Soft preference**: a like, dislike, cuisine, budget, cooking-time or
  meal-feedback note with a date and source. Editable and deletable by the
  patient; deletions are remembered. Continues today's preference memory.
- **Recipe / planned meal**: a structured suggestion: name, ingredients with
  quantities, texture, steps, preparation time, equipment, and nutrient
  totals computed from the food database.
- **Check result**: for one recipe against one profile version: pass or
  fail, the rules evaluated, the values compared, the attempt number and
  the reasons on failure.
- **Recommendation record**: what was shown to the patient, with the profile
  version and check result it carried.
- **Meal history record**: a planned, eaten or rejected meal with its date
  and, for rejections, the reason.
- **Red-flag rule**: a pattern, a fixed safe response and a label, kept in a
  file maintained by dietitians. A **red-flag escalation** records a match:
  patient, message, rule, time, notification status and review decision.
- **Reference tables**: allergen groups and drug-food interactions, kept as
  clinician-editable data files with a version.
- **Review item**: a pending entry, a rule conflict, an escalation or a
  sampled plan awaiting a clinician decision, with the decision and date
  once made.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Across the full eval set, 0 suggestions shown to a patient
  violate a confirmed hard constraint (allergen, interaction, nutrient
  limit, texture, physical limitation, diet setting).
- **SC-002**: A hard fact stated mid-conversation and confirmed by the
  patient is enforced on the next recipe in that conversation in 100% of
  eval cases.
- **SC-003**: In sessions after the one where a fact was confirmed, 100% of
  confirmed hard facts are applied (recall of earlier-session facts).
- **SC-004**: Extraction of hard facts reaches at least 95% recall and 90%
  precision against the hand-labelled profiles; soft preferences at least
  85% for both, measured on a held-out synthetic set. Precision of the
  accept band is at least 98%. No fact that removes or loosens a constraint
  is ever applied without a patient or clinician action.
- **SC-005**: When a needed clinical value is missing, the coach abstains
  (asks or defers, no invented number) in 100% of eval cases.
- **SC-006**: Nutrient totals attached to a suggestion are within 5% of the
  totals computed directly from the food database for the same
  ingredients.
- **SC-007**: Every red-flag phrase in the dietitians' list, and every
  paraphrase they marked, gets the fixed response; no more than 1% of
  ordinary eval messages are screened.
- **SC-008**: Ordinary chat turns are no slower than before the feature.
  A recipe request, including checks and up to three tries, completes
  within the budget set at planning (proposed: 90% under 12 seconds).
- **SC-009**: Every recommendation shown can be traced to its profile
  version and check result.
- **SC-010**: Patients can find, correct or delete a remembered preference
  from the app in under one minute.
- **SC-011**: Phases 1 to 3 ship and pass the eval with Phases 4 to 6
  absent.

## Phases and delivery order

One pull request per phase, in this order. Phases 1 to 3 ship first and
must work without 4 to 6. The eval set is built alongside Phases 1 and 2
and runs in continuous integration from Phase 2 onward.

| Phase | Delivers | Stories |
|---|---|---|
| 1 | Structured profile store with history and states; migration of existing conditions, diet settings and restrictions; profile block in every recipe and plan prompt | US1 |
| 2 | Structured recipes; deterministic checker; nutrient totals from the food database; regenerate-or-drop; failure logging; clinician-editable allergen and interaction tables; eval set in CI | US2 |
| 3 | Red-flag screen before any model call; fixed responses; staff notification | US3 |
| 4 | Post-turn extraction; pending hard facts with same-session read-back and confirmation; direct soft-preference saves | US4 |
| 5 | Soft-preference and meal-history store; relevance retrieval plus three-week variety; patient view, correct and delete | US5 |
| 6 | Dietitian review queue with approve, reject and edit | US6 |

## Assumptions

- **Everyone is a patient.** The feature applies to every Mealsy user with
  no enrolment step. "Patient" and "user" are the same person; the app's
  own copy keeps saying "you".
- **One memory, not two.** The profile store extends the existing
  preference memory: hard entries gain history, provenance and state; soft
  preferences keep today's rules plus a date. Existing restriction facts,
  declared conditions and diet settings migrate into it as confirmed,
  patient-sourced entries. Diet settings stay editable from Settings as
  today but are stored once.
- **Structured suggestions everywhere.** Any coaching reply that proposes a
  specific meal or recipe goes through the structured form and the checker,
  including the quick "what should I have for dinner?" path. Answers that
  suggest no specific food (readbacks of intake, general guidance) are not
  checked. Spec 012's weekly plans use the same checker; this spec provides
  the mechanism its restriction and condition requirements assume.
- **Maximum tries**: 3 generations per recipe, counting the first.
- **Fluid limits** are checked against the water content of ingredients in
  the food database, including drinks, and are labelled approximate.
- **Interaction tables** start with a small, clinician-reviewed set of
  well-documented interactions (for example anticoagulants and vitamin K,
  MAOIs and tyramine-rich foods, some statins and grapefruit). Medications
  are matched by name in the file; unmatched medications produce no
  interaction rule and are listed as "no known rule" for the dietitian.
- **Soft-preference retrieval** uses the semantic search the app already has
  for other content; no new memory product is introduced.
- **Confirmation in chat** reuses the existing "waiting for your answer"
  mechanism; spec 010 governs how a reply is told apart from a new message.
- **Encryption at rest** is provided by the managed database the app
  already runs on, which encrypts stored data by default; no application-
  level field encryption is added under GDPR.
- **Android only** for patient-facing screens. The web app stays frozen.
- **Prior consumer facts** (likes, habits, context) already stored are kept
  as soft preferences with their existing dates.

## Decisions (owner, 2026-11-12)

- **Clinician is a placeholder (Q1).** No clinician accounts, role or
  screen are built. The data model keeps source "clinician" and the review
  queue is a backend queue the team operates through a protected
  administrative interface. "Clinician-set" nutrient limits are entered
  that way or, when a patient reports one, saved as pending and confirmed
  by the patient. Phase 6 delivers the queue and its actions, not a screen.
- **GDPR, approved list A plus Fastino (Q2, revised 2026-11-13).** Approved
  for patient data: the database host, the application host, the LLM
  provider, the observability service and the typed-judgment service
  (Fastino GLiDE). GLiDE keeps routing, and scores inferred facts and
  coaching replies. Before this ships: a data processing agreement with
  Fastino and the privacy notice naming it as a processor. The push
  provider receives tokens and profile-free notification text only.
- **Notification channel (Q3, default chosen by the spec, not yet
  confirmed).** Red-flag escalations are stored as records and sent to a
  configurable webhook address (Slack-compatible), which needs no new
  dependency. When no address is configured the escalation is stored and a
  loud error is logged, so the screen still works without a recipient.
  Email is not added. Change this decision here if another channel is
  wanted.

- **Inferred facts may bind (Q4, 2026-11-13).** Hard facts inferred with
  high probability bind without asking, but only when they add a
  constraint. They show as "inferred" in the profile, and the coach
  mentions each one once. Facts that remove or loosen a constraint always
  need the patient's confirmation.

## Out of Scope

- Medical advice, diagnosis, medication guidance or setting clinical
  targets; the coach declines these.
- Model fine-tuning.
- Warning on *logged* meals that conflict with an allergy (spec 010 covers
  logging-side awareness).
- Household or multi-patient profiles.
- Any web app change. No review screen is built; the queue is backend-only.
- Adding new declarable conditions beyond what the profile types allow.
