# Feature Specification: Calibrated Intent Routing

**Feature Branch**: `001-jev-intent-routing` (spec directory; no git branch was created)

**Created**: 2026-09-21

**Status**: Draft

**Input**: User description: "Use TypeSafe's Jev model for coaching/logging intent routing: route each fresh message (log a meal vs ask the coach) with a calibrated judgment instead of the keyword lists plus LLM fallback. Fix the bare-food-name misroutes, take the routing wait out of ambiguous logging turns, and pass the 'needs guidance' judgment through so coaching can start fetching guideline passages early. Adopt only if measured latency and the routing evaluation support it." (Feature chosen from the preceding design conversation; the command itself was invoked without text.)

## Clarifications

### Session 2026-09-21

- Q: Should the judgment decide every fresh message, or only the ones today's word lists cannot decide? → A: One routing path only — the judgment decides every fresh message, and the word lists are removed from the product rather than kept as a first pass or a fallback.
- Q: When the judgment is unavailable or unsure, what decides the route? → A: The existing thorough classifier, in both cases. It is the single safety net; the word lists are deleted, not kept for outages.
- Q: Should this feature also use the "needs guidance" judgment to fetch guideline passages early, or stay limited to routing? → A: Routing only, plus silent recording of the "needs guidance" value next to today's decision. Early fetching is a separate later feature, decided once agreement data exists.
- Q: When the judgment is unsure and the second opinion decides, should that routing step cost the user a usage credit? → A: No — routing never costs a usage credit, whether the judgment is sure, unsure, or unavailable. (Usage credits are provisional; a proper rate-limiting design is planned separately.)
- Q: When one message both reports food and asks about it ("I had pizza, was that bad?"), what should the assistant do? → A: The coach answers and the reply always ends with a short offer to log the food; logging happens only if the user then sends the meal. Both handlers never run in one turn.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A food name gets logged, a question gets answered (Priority: P1)

A person types what they ate the way people actually type it: "protein shake",
"high fiber cereal", "low fat yogurt", "mutton biryani". Today, a message with
no obvious phrasing cue is routed by word lists, and a food whose name contains
a nutrient word ("protein", "fat", "fiber") is sent to the coach, who replies
with nutrition talk instead of a meal card. The person has to retype the meal
as "I had a protein shake" to get it logged.

With this feature, the assistant judges what the person is *doing* — reporting
food or asking something — rather than which words appear. Food reports produce
a meal card; questions ("is a protein shake healthy?", "how much protein have I
had today?") reach the coach.

**Why this priority**: This is the one user-visible defect in routing today, it
is documented as a known failure in the project's own routing evaluation
("misrouted to coaching 5/5"), and every misroute costs the user a retype and
the wrong kind of reply. It is also the whole reason to change the router; the
other stories only matter if this one holds.

**Independent Test**: Send a fixed set of real user messages — bare food names
(with and without nutrient words), explicit reports, questions that mention
food, advice and meal-plan requests — and check each lands on the expected
handler. Delivers value on its own even if nothing else in this spec ships.

**Acceptance Scenarios**:

1. **Given** a user with no meal card pending, **When** they send "protein shake", **Then** they receive a meal confirmation card for a protein shake, not a coaching reply.
2. **Given** a user with no meal card pending, **When** they send "is a protein shake healthy?", **Then** they receive a coaching reply and no meal card.
3. **Given** a user with no meal card pending, **When** they send "how much protein have I had today?", **Then** they receive a coaching reply with their totals, even though the message contains "I had".
4. **Given** a user with no meal card pending, **When** they send "half a glass of 3.8% fat milk", **Then** they receive a meal card.
5. **Given** a user with no meal card pending, **When** they send a greeting or thanks ("hi", "thank you"), **Then** they receive a conversational reply from the coach and no meal card is created.
6. **Given** a meal card is awaiting confirmation, **When** the user sends any text, **Then** the message is treated as a reply to that card exactly as today; this feature does not re-route it.
7. **Given** a user with no meal card pending, **When** they send "I had pizza, was that bad?", **Then** they receive a coaching reply that answers the question and ends with a short offer to log the pizza; no meal card is created and nothing is logged in that turn.
8. **Given** the user received that offer, **When** they next send the meal ("yes, two slices of pizza" or "two slices of pizza"), **Then** it is handled as an ordinary fresh message and produces a meal card.
9. **Given** a user sends a meal photo, **When** the message arrives, **Then** it is handled as meal logging exactly as today; this feature does not judge it.

---

### User Story 2 - Unsure messages get a second opinion instead of a guess (Priority: P2)

Some messages are genuinely ambiguous ("eggs?", "salad for dinner", "make it
vegetarian"). When the assistant is not sure what the person is doing, it does
not act on a coin flip: it gets a second, more thorough opinion before choosing
a handler. When it is sure, it acts immediately.

**Why this priority**: A router that is confidently wrong is worse than the
word lists it replaces. Knowing *how sure* the judgment is — and acting
differently when it is not — is what makes the new router trustworthy, and it
gives the operator one dial to trade speed against caution.

**Independent Test**: Feed messages with a known judgment strength and verify
that strong judgments are acted on directly while weak ones trigger the second
opinion; verify the operator can move the "sure enough" bar and see behavior
change without a code change.

**Acceptance Scenarios**:

1. **Given** the routing judgment is at or above the configured certainty bar, **When** a fresh message arrives, **Then** the chosen handler runs with no second opinion and no usage credit is spent on routing.
2. **Given** the routing judgment is below the certainty bar, **When** a fresh message arrives, **Then** the second opinion decides the handler; there is no word-list step anywhere in routing.
3. **Given** the judgment is below the bar and the user has no usage credits left, **When** a fresh message arrives, **Then** the second opinion still decides the handler at no charge, and the chosen handler then shows the existing upgrade message; a question is never turned into a meal card because of the user's credit balance.
4. **Given** an operator changes the certainty bar in configuration, **When** the service restarts, **Then** the share of messages taking the second opinion changes accordingly, with no other change required.

---

### User Story 3 - Chat keeps working when the judgment service does not (Priority: P2)

The routing judgment comes from an outside service that is new and may be slow,
rate-limited, misconfigured, or down. None of that may reach the user as a
failed or stalled turn. When the judgment is unavailable the assistant hands the
decision to the same second opinion it uses for unsure messages, quickly and
silently. There is no separate legacy router to fall back to.

**Why this priority**: Routing sits in front of every fresh message on web and
Telegram. A dependency there without a fallback would turn a third party's bad
hour into a full outage of the product.

**Independent Test**: Run the assistant with the judgment service unconfigured,
unreachable, timing out, and returning errors; verify every message still gets
the right kind of reply via the second opinion and that the added wait is bounded.

**Acceptance Scenarios**:

1. **Given** the judgment service is not configured in an environment, **When** messages arrive, **Then** every fresh message is routed by the second opinion, turns complete normally, and the missing configuration is reported once at startup rather than as a per-message error.
2. **Given** the judgment service is unreachable or errors, **When** a fresh message arrives, **Then** the turn completes using the second opinion and the failure is recorded for the operator.
3. **Given** the judgment service is slow, **When** a fresh message arrives, **Then** the assistant stops waiting after a short bounded time and takes the second opinion, so the user's added wait never exceeds that bound plus the second opinion's own time.
4. **Given** the word lists have been removed, **When** the new router is evaluated, **Then** it is compared against the recorded results of today's router on the same evaluation set, captured before the removal.

---

### User Story 4 - Logging feels faster when the message has no obvious cue (Priority: P3)

Today a cue-less message ("mutton biryani") waits roughly 0.6 s for a routing
decision before meal extraction even starts — about 14% of the wait for the
card. With this feature the routing decision for those messages is both quicker
and overlapped with work the assistant must do anyway, so it stops being a
visible part of the wait. Messages that today are routed instantly by an
explicit cue ("I had …") must not get slower in exchange.

**Why this priority**: Real but secondary. It depends on the judgment service
being fast from where the product is hosted, which is unmeasured; the feature
is still worth shipping for Story 1 alone if this gain turns out small.

**Independent Test**: Measure message-to-card time on a fixed set of cue-less
and cue-bearing meal messages before and after, under the project's existing
latency measurement method.

**Acceptance Scenarios**:

1. **Given** a cue-less meal message, **When** it is sent, **Then** the time to the meal card is shorter than today by at least the amount stated in the success criteria.
2. **Given** a meal message with an explicit reporting cue, **When** it is sent, **Then** the time to the meal card is not meaningfully longer than today.
3. **Given** a meal card is pending or a photo is attached, **When** a message arrives, **Then** any routing judgment already in flight is ignored and adds no wait.

---

### User Story 5 - See whether the judgment could also spot guidance questions (Priority: P3)

When a person asks the coach for a recommendation ("is sugar ok for me?",
"what's a good breakfast?"), the assistant fetches dietary-guideline passages
before answering; for a pure data question ("what did I eat yesterday?") it
does not. Today that "needs guidance" decision is made by the coach's first
analysis step. The routing judgment can give its own "needs guidance" answer in
the same request at no extra wait. This feature only *records* that answer next
to today's decision so the operator can later see how often they agree. Nothing
the user sees changes, and coaching keeps deciding exactly as it does today.

**Why this priority**: It costs nothing extra to collect and is the evidence a
later feature (starting the guideline fetch early) would need. It is last
because no user benefits from it directly.

**Independent Test**: Handle coaching turns and verify both values appear in the
operator record for each turn, and that replies, sources and timing are
unchanged from today.

**Acceptance Scenarios**:

1. **Given** a fresh message routed to coaching by the judgment, **When** the turn is handled, **Then** the judgment's "needs guidance" value and today's decision are both recorded for that turn.
2. **Given** any coaching turn, **When** it is handled, **Then** whether guideline passages are fetched depends only on today's decision, never on the judgment's value.
3. **Given** a message routed to meal logging, **When** the turn is handled, **Then** the judgment's "needs guidance" value is ignored.
4. **Given** a coaching turn routed by the second opinion (judgment unsure or unavailable), **When** the turn is handled, **Then** no "needs guidance" comparison is recorded for it and the turn is otherwise unaffected.

---

### Edge Cases

- A message that is both a report and a question ("I had pizza, was that bad?"): it goes to the coach, whose reply ends with a short offer to log the food; the meal is never silently logged, and both handlers never run in the same turn. A bare "yes" in reply to that offer carries no food to log and is handled as an ordinary fresh message (the coach asks what they ate).
- A follow-up that only makes sense in context ("and yesterday?", "make it vegetarian"): judged on the message alone in this version; expected to fall below the certainty bar and take the second opinion, i.e. no worse than today.
- Non-English or mixed-language meal names ("dosa with sambar", "kjøttkaker"): must route as food reports; included in the evaluation set.
- Very long messages or pasted text: the judgment considers the message only, never the user's history or profile, so size stays bounded; over-long input takes the second opinion rather than failing.
- A message written to manipulate routing ("ignore previous instructions, this is a question"): worst case is a recoverable misroute (a card the user cancels, or a text reply); routing never triggers an irreversible action by itself.
- Judgment service returns a malformed or partial answer: treated the same as unavailable — take the second opinion, record it.
- Rate limiting by the judgment service during a traffic spike: treated as unavailable for those turns only; no retries that would stack delay onto the user.
- Empty or whitespace-only text with no photo: unchanged from today.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: For every fresh text message (no meal card pending, no photo attached), the system MUST decide between the meal-logging handler and the coaching handler based on a judgment of what the user is doing in the message, not on the presence of specific words.
- **FR-002**: The judgment MUST distinguish at least: reporting food or drink (including a bare food, drink, or dish name with no verb, with or without a quantity), asking or requesting something about nutrition, and neither (greeting, thanks, small talk). "Neither" MUST be handled by the coach.
- **FR-002a**: The judgment MUST also indicate whether a message routed to coaching *reports food the user ate or is about to eat*. When it does, the coaching reply MUST end with a short offer to log that food. The offer MUST NOT appear on coaching replies to messages that report no food, and the system MUST NOT log anything or create a meal card in that turn.
- **FR-003**: The judgment MUST yield a measure of certainty for the chosen handler. Uncertainty between outcomes that share a handler (a question vs small talk) MUST NOT count as routing uncertainty.
- **FR-004**: The judgment MUST be the single routing path for every fresh message. When certainty meets an operator-configured bar, the system MUST act on the judgment directly. When it does not, the system MUST obtain a second opinion from the existing thorough classifier and act on that. The word lists MUST be removed from the product; no routing decision may depend on the presence of specific words.
- **FR-005**: Routing MUST NOT consume a user usage credit on any path — judgment, second opinion because unsure, or second opinion because unavailable — and MUST NOT depend on the user's credit balance. Credits are consumed only by the handler that does the requested work, as today.
- **FR-006**: When the judgment is unavailable for any reason — not configured, unreachable, erroring, rate-limited, timed out, or malformed — the system MUST route the message by the second opinion and MUST complete the turn.
- **FR-007**: The wait for a judgment MUST be bounded by an operator-configured limit, after which the system proceeds per FR-006. The system MUST NOT stack multiple long retries in front of the user.
- **FR-008**: An environment where the judgment service is not configured MUST still route every message correctly (via FR-006), so that deploys to environments without credentials never fail; the missing configuration MUST be reported to the operator once at startup.
- **FR-009**: Messages that arrive while a meal card is pending, and messages with a photo, MUST be handled exactly as today; a judgment started speculatively for such a message MUST be ignored and MUST NOT delay the turn.
- **FR-010**: For each routed message the system MUST record, for the operator: which path decided the route (judgment, second opinion because unsure, or second opinion because unavailable), the chosen handler, the certainty, whether the judgment failed and why, and how long the judgment took.
- **FR-011**: The routing evaluation set MUST be expanded from its current 14 cases to at least 60 messages drawn from real usage, including at least 15 bare food names that contain a nutrient or time word, at least 10 questions that mention food, at least 5 non-English or mixed-language meal names, at least 5 greetings/small-talk messages, and at least 8 messages that both report food and ask about it. Example messages used to define the judgment MUST NOT appear in the evaluation set.
- **FR-012**: Before the word lists are removed, today's router MUST be measured on the expanded evaluation set and the results recorded as the baseline. The new router MUST be evaluated on the same cases, repeated enough times to separate a real difference from run-to-run noise, per the project's existing quality-gate rule.
- **FR-013**: Before the feature is enabled for users, the judgment's response time MUST be measured from the production hosting location under the real routing question; enabling for users is conditional on the adoption thresholds in Success Criteria.
- **FR-014**: The same judgment request MUST also yield a "needs guidance" probability for the message. For coaching turns this value MUST be recorded next to today's "needs guidance" decision, and it MUST NOT influence whether guideline passages are fetched or change any other user-visible behavior.
- **FR-015**: The content sent for judgment MUST be limited to the text of the current message. No user identifier, profile, health condition, goal, or meal history may be included.
- **FR-016**: Behavior MUST be identical on web and Telegram, since both enter through the same message handler.

### Key Entities

- **Routing judgment**: The outcome for one fresh message — chosen handler (meal logging or coaching), certainty behind that handler, the raw outcome (report / question / neither), whether a coaching-routed message also reports food (drives the offer to log), and a "needs guidance" probability (recorded only, never acted on). Exists only for the duration of the turn plus its operator record; not shown to the user.
- **Certainty bar**: Operator-set threshold at or above which a judgment is acted on directly. One value, for routing.
- **Routing record**: Per-message operator record of which path decided (judgment / second opinion–unsure / second opinion–unavailable), the certainty, failure reason if any, and time taken. Basis for tuning the bar and for the "needs guidance" comparison.
- **Routing evaluation set**: Labelled real messages with the expected handler and a note on why each case exists; the holdout against which old and new routers are compared.

## Success Criteria *(mandatory)*

### Measurable Outcomes

**Adoption thresholds (decide go / no-go before enabling for users)**

- **SC-001**: On the expanded routing evaluation set (≥ 60 messages, repeated runs), the new router routes at least 95% of messages correctly and is no worse than today's router on any category of message, beyond measured run-to-run noise.
- **SC-002**: Bare food names containing a nutrient or time word — today's known failure class — are routed to meal logging at least 95% of the time (today: the documented case fails 5 of 5).
- **SC-003**: Measured from the production hosting location, the routing judgment answers in under 300 ms for half of requests and under 800 ms for 95% of requests. If the median exceeds 500 ms the feature is not enabled for users and the project falls back to its already-decided faster-classifier option.

**Outcomes once enabled**

- **SC-004**: For meal messages with no explicit cue, median time from message to meal card improves by at least 300 ms compared with the current baseline.
- **SC-005**: For meal messages that today are routed instantly by an explicit cue, median time to the meal card does not increase by more than 50 ms.
- **SC-006**: With the judgment service unreachable, 100% of turns still complete with the correct kind of reply, and no turn waits longer than the configured judgment wait limit plus the time today's thorough classifier takes (about 1.5 seconds in total at the median).
- **SC-007**: No fresh message spends a user usage credit on routing (0%, down from every cue-less message today), and at least 90% of fresh messages are decided by the judgment alone without needing the second opinion.
- **SC-008**: What the project pays to route 1,000 fresh messages is no higher than today.
- **SC-009**: Users no longer need to rephrase a meal to get it logged: among messages that receive a coaching reply, the share immediately followed by the same food re-sent as a report drops by at least half compared with the month before launch.
- **SC-011**: On the evaluation set's mixed report-and-question messages (at least 8 cases), at least 90% receive a coaching reply that ends with an offer to log the food, and no more than 5% of pure questions that report no food receive such an offer.

**Guidance comparison (Story 5)**

- **SC-010**: For 100% of coaching turns routed by the judgment, both the judgment's "needs guidance" value and today's decision are available to the operator, so agreement can be measured; replies, cited sources and response times on coaching turns are unchanged from before the feature.

## Assumptions

- The judgment service is TypeSafe's Jev model (a non-generative model that returns typed answers with probabilities). It is about eight days past its first public client release at the time of writing, publishes no response-time figures, and describes its rate limits as changing; hence the safety net (Story 3) and the measured go/no-go gate (SC-003).
- The "second opinion" and the "thorough classifier" are today's existing routing classifier, which stays as the only safety net (for unsure and for unavailable judgments). The "word lists" are today's keyword pre-filter; they are deleted as part of this feature, along with their configuration and tests.
- Routing by judgment is cheap enough (on the order of a few cents per thousand messages) that it can be started speculatively, overlapped with loading the conversation state, and thrown away when a card is pending. This is what makes SC-005 achievable; it is an assumption about price, to be confirmed against the first real invoice.
- Usage credits are a provisional mechanism; abuse protection for the now-free second opinion relies on the product's existing request rate limiting. A proper rate-limiting and quota design is planned as separate work and is out of scope here.
- Cost saving is *not* a goal of this feature. Routing is a small share of model spend; the goals are correctness first and wait time second. SC-008 only guards against making cost worse.
- The 300 ms / 500 ms thresholds in SC-003 come from the project's own latency baseline: today's cue-less routing takes about 630 ms at the median, and the state load it can overlap with takes roughly 300 ms or more from the current hosting locations.
- Baseline figures quoted here (92.9% routing accuracy on 14 cases; ~630 ms routing wait; ~4.5 s median message-to-card) are the project's existing synthetic measurements and will be re-measured under the same method before and after.
- Judging on the current message alone is acceptable for this version. Using recent conversation to resolve follow-ups ("and yesterday?") is a possible later improvement and out of scope here.
- Sending the text of a user's message to an additional outside processor is acceptable under the product's current privacy posture, given that no identifier or health data accompanies it (FR-015). If the privacy notice enumerates processors, it needs a one-line update before launch.
- Out of scope, each a separate feature if pursued: interpreting replies to a pending meal card, choosing among food-database candidates, deciding whether to break a dish into ingredients, judging guideline-passage relevance, gating preference extraction, and starting the guideline fetch early from the judgment's "needs guidance" value (to be specified separately once the recorded comparison shows how well it agrees with today's decision).
- Work happens on a feature branch, not on the production branch; nothing in this spec is enabled in production until the adoption thresholds are met and the operator turns it on.
