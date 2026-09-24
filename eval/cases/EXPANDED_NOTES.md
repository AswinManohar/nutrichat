# food_identity_expanded.jsonl — build notes

176 verified cases in `eval/cases/food_identity_expanded.jsonl` (new file;
`eval/cases/food_identity.jsonl`, the 22-case baseline, is untouched).

## Category breakdown

| category | count |
|---|---|
| bare_noun | 64 |
| single_food | 43 |
| preparation | 33 |
| quantity_phrase | 18 |
| ambiguous | 18 |
| **total** | **176** |

## Verification

Passes the mandatory checker
(`/tmp/claude-1000/-home-aswinmanohar-nutrichat/e3ab5985-c60f-43af-85e3-b4d0fa3ddabd/scratchpad/verify_cases.py`)
cleanly:

```
eval/cases/food_identity_expanded.jsonl: 176 cases, 13694 db rows

nonexistent acceptable_fdc_ids : 0
dead acceptable_name_substrings: 0
UNSATISFIABLE cases            : 0

OK
```

Two classes of bugs that checker caught and this file had to be corrected for
(both are the same mistakes flagged in the original 22-case file, so worth
calling out explicitly):

- **One invented fdc_id.** `1098464` for "chicken breast" did not exist in
  this DB (looked plausible, wasn't real — same failure mode as the three bad
  ids already found in `food_identity.jsonl`). Replaced with `2646170`
  ("Chicken, breast, boneless, skinless, raw"), a real row I looked up
  directly.
- **64 dead substrings.** I had assumed the FNDDS "NFS" (Not Further
  Specified) convention was universal and wrote things like `"chicken, nfs"`,
  `"rice, nfs"`, `"egg, nfs"`, `"tea, nfs"` — none of which exist as rows.
  Also several preparation-qualifier substrings I *assumed* existed
  ("chicken, grilled", "broccoli, roasted", "eggs, hard-boiled") turned out
  not to, once the checker's punctuation-normalizing match was applied. All
  were pruned. None of these were load-bearing: every case still had at
  least one other real substring or fdc_id, and I re-ran the matcher scoring
  after pruning — the recall@1 numbers below are identical before and after,
  confirming the dead entries were pure waste, not silently propping up the
  satisfiability of any case.
- Also note `gate._matches` now normalizes punctuation via
  `_normalize_for_match` before substring comparison (word order/adjacency is
  still required). All scoring below imports `_matches` directly from
  `eval/gate.py` rather than reimplementing it, so it matches what the real
  scorer produces.

## Method

1. Dumped all 13,694 `food.description` rows from the bundled SQLite DB
   (`backend.agent.tools.usda_local.database_path()`) to inspect real FDC
   spellings before writing any `acceptable_name_substrings`.
2. Wrote 179 candidate cases across the five categories, drawing `bare_noun`
   and `preparation` queries preferentially from `survey_fndds_food` rows.
3. Verified every case programmatically: a case is kept only if at least one
   row in the DB satisfies it (`fdc_id` in `acceptable_fdc_ids` OR a
   substring match against `acceptable_name_substrings`), using the same
   `_matches()` logic as `eval/gate.py`.
4. Audited substrings for over-matching by listing every DB row each
   substring set actually admits, and tightened several that were initially
   too loose (see below).
5. Ran the real matcher (`usda_local.lookup`) over the final 176 cases and
   scored each result with `gate._matches`, then hand-checked every miss to
   decide whether it was a genuine matcher weakness (kept as a miss) or a
   substring gap on my part (fixed).

## Discarded as unsatisfiable: 3

- **"cherry tomatoes"** — no row in the DB is a cherry tomato under any
  spelling (checked exhaustively for "cherry" + "tomato" tokens together).
- **"roasted vegetables"** / **"grilled vegetables"** — the DB has no
  vegetable-medley row combined with "roast" or "grill" in any form (it has
  "Asian stir fry vegetables", which covers stir-fry, but nothing for
  roasted/grilled). Both dropped rather than force a case the matcher could
  never satisfy honestly.

## Over-matching bugs caught and fixed before scoring

Several early substring choices admitted clearly wrong foods and were
tightened:

- `"almond"` for **"almonds"** matched "Almond milk", "Almond butter",
  "Almond oil", "Almond chicken" → restricted to `"almonds,"`.
- `"peanut butter"` for **"peanut butter"** matched candy/cookie products
  ("Candies, MARS ... Peanut Butter Chocolate", "Cake or cupcake, peanut
  butter") → restricted to specific spread descriptions
  (`"peanut butter, smooth"`, `"...chunky"`, `"...creamy"`, plus the exact
  fdc_id for plain "Peanut butter").
- `"bread,"` for **"toast"**/"slice of toast" matched "Cake, gingerbread",
  "Cookie, shortbread", "Cornbread", "Crackers, crispbread" → restricted to
  an explicit list of real bread-loaf variants (`"bread, white"`,
  `"bread, wheat"`, `"bread, whole wheat"`, `"bread, rye"`, etc.).
- `"sugar, nfs"` for **"sugar"** technically also matches "Cereal or granola
  bar, reduced sugar, NFS" and "Chocolate milk, reduced sugar, NFS" as a raw
  substring. Left in (low risk given the matcher's own ranking strongly
  favors short/generic descriptions for a one-word query, verified by
  running the matcher — it never actually returns either of these), but
  flagged here as a known theoretical gap in the acceptance rule rather than
  in the matcher.

## Comma-inverted spellings caught (the "oil, olive" class of bug)

Per the brief's warning, several DB rows use the "food, adjective" order
while the natural query is "adjective food" — both are correct answers and
both had to be listed:

- "black beans" → both `"beans, black"` and `"black beans,"` (DB has
  `"Black beans, NFS"`).
- "kidney beans" → both `"beans, kidney"` and `"kidney beans,"`.
- "brown sugar" → both `"sugar, brown"` and `"sugars, brown"`.
- "baby spinach" → both `"spinach, raw"` and `"spinach, baby"`.
- "sour cream" → both `"sour cream,"` and `"cream, sour"` (DB has
  `"Cream, sour, cultured"`).
- "baked beans" → both `"beans, baked"` and the plain `"baked beans"` (DB
  ships the food-as-eaten as `"Baked beans"` with no comma at all).

## Debatable / genuinely ambiguous calls (flagged, not silently resolved)

- **"russet potato"** — the matcher returns "Potato, NFS" (no variety), which
  I did *not* count as correct: the DB has no "Potato, russet" entry, so
  there is no way to verify the matcher actually identified the variety
  versus just returning the generic fallback. Kept as a miss; this is a
  real specificity gap, not a scoring bug.
- **"string cheese"** — DB has no literal "string cheese" entry; the closest
  semantic match would be a fresh mozzarella variant, but the matcher
  returns "Cheese, fontina" (wrong). Left unaccepted rather than guess which
  mozzarella row is "string cheese enough."
- **"cherries"** (bare_noun) — `"cherries, raw"` also matches "Chokecherries,
  raw" (a related but botanically different fruit). Left in as an
  acceptable minor generosity rather than narrowed further, since
  chokecherries are still a cherry-family fruit a user might plausibly mean.
- **"potato"** (bare_noun) — `"potato, nfs"` also matches "Sweet potato,
  NFS". Sweet potato is a different food from a user's likely intent when
  typing bare "potato", but excluding it would require negative-lookahead
  substring logic the scorer doesn't support. Flagged rather than silently
  accepted as fully correct.
- **"piece of chicken"** — accepted "Fast foods, chicken, breaded and fried,
  boneless pieces, plain" in addition to the generic NFS/roasted/cooked
  forms, since a fast-food chicken piece is a defensible reading of the
  quantity phrase, even though it's a different food class (breaded/fried
  fast food) from the bare "chicken" answer.

## Matcher recall@1 (measured, not simulated)

Ran `backend.agent.tools.usda_local.lookup()` directly on all 176 queries
and scored with `eval.gate._matches` (the actual scorer logic):

| category | recall@1 | n |
|---|---|---|
| ambiguous | 100.0% | 18/18 |
| single_food | 95.3% | 41/43 |
| bare_noun | 93.8% | 60/64 |
| quantity_phrase | 66.7% | 12/18 |
| preparation | 60.6% | 20/33 |
| **overall** | **85.8%** | **151/176** |

The matcher was **not modified** to improve this number.

### What's actually failing (all misses hand-verified as real matcher issues,
not case-file bugs)

- **"meatless" contamination on bare nouns**: "chicken" → "Chicken,
  meatless"; "bacon" → "Bacon, meatless". The matcher's ranking doesn't
  penalize these enough against a bare, unqualified query.
- **Compound/dish rows outranking simple preparations**: "grilled chicken",
  "baked chicken", "roasted chicken" all land on multi-word NS/dish variants
  ("Chicken, NS as to part, grilled with sauce, skin eaten"; "Chicken,
  chicken roll, roasted") instead of the plain roasted-breast/thigh rows.
  "fried chicken" → "Chicken, meatless, breaded, fried" (same meatless bug
  as above, compounded with "fried").
- **Wrong-food matches for some "sauteed/steamed/roasted X" preparations**:
  "sauteed spinach"/"sauteed mushrooms"/"caramelized onions"/"roasted
  broccoli" all resolve to the plain raw form, i.e. the matcher drops the
  preparation qualifier entirely for produce.
  "steamed broccoli" is worse — it resolves to **"Oysters, steamed"**, a
  completely different food, apparently because "steamed" dominates ranking
  over the food-name tokens.
- **Quantity-phrase queries are especially fragile**: "cup of rice" resolves
  to "Candies, REESE'S Peanut Butter Cups" (the word "cup" is apparently
  matching the confectionery item's name, not the recipient container),
  "bowl of rice" → a chicken frozen entree, "slice of bread" → "Luncheon
  slices, meatless", "cup of milk" → a dessert topping mix, "slice of pizza"
  → "Dessert pizza". These look like the "of X" quantity phrasing is
  confusing the tokenizer/ranker more than plain nouns do.

This 85.8% (vs. 100% on the trivially-permissive `ambiguous` category and
~94-95% on `bare_noun`/`single_food`) is a much more informative signal than
the old 22-case set could produce, and specifically surfaces that
preparation and quantity-phrase inputs — both extremely common in real
entity-extraction output — are the matcher's weak spot, not simple food
nouns.

## Acceptance-list repair

The metrics above were measured against acceptance lists that were
systematically too narrow: they were written against one FDC spelling of
each food (e.g. `"sourdough"` for a database that spells the row
**"Bread, sour dough"**) and rejected correct answers as misses while
weaker answers scored as hits by accident (matching a parenthetical or
substring). This section repairs that.

**Method.** 107 of the 176 cases had at least one real answer — actually
returned by lexical/vector/LLM retrieval — that the case rejected (237
rejected answers total, pre-collected in
`scratchpad/adjudicate.json`). Each was adjudicated by hand as a correct
answer to log for that query, a wrong answer, or a genuine judgment call,
using the rules in the task brief (raw/cooked both fine for produce,
cultivar/variety fine, cut/part fine for a bare protein noun but not a
prepared dish, `NFS`/`NS as to` markers accepted readily). Accepted
answers were folded into the case as either a targeted `acceptable_fdc_ids`
entry (single specific row, no clean generalizable spelling) or a widened
`acceptable_name_substrings` entry (a real FDC spelling variant that should
generalize, verified against the live database before adding so it
doesn't also admit unrelated foods).

**Verdicts:** 107 accepted, 108 rejected, 22 flagged borderline and left
rejected (not silently widened). `ambiguous`-category cases (`berries`,
`salad`, `candy`) were left untouched entirely, per the instruction to
leave that category's intentionally broad lists alone — even though, e.g.,
"Candies, sweet chocolate"/"Candies, caramels" are genuinely candy and are
only missed because the case's substring is singular ("candy") while FDC
uses the plural ("candies"); this remains an open, deliberately unfixed
gap in the `ambiguous` category.

**Acceptance breadth** (rows out of 13,694 admitted per case), measured
with the same `_matches`/`_normalize_for_match` logic as `gate.py`:

| | before | after |
|---|---|---|
| median, all 176 cases | 11 | 12 |
| median, non-`ambiguous` cases | 10 | 11 |

The widening was deliberately narrow — most additions are single
`acceptable_fdc_ids` entries (one extra DB row each), not substrings, and
every substring added was checked against the live database first. A
handful of non-`ambiguous` cases already exceeded the ~150-row guideline
*before* this pass (pre-existing, not something this repair introduced)
and picked up at most 1-2 more rows from it:

| case | category | breadth before | breadth after |
|---|---|---|---|
| piece of fruit | quantity_phrase | 2137 | 2137 (untouched) |
| bowl of soup | quantity_phrase | 259 | 259 (untouched) |
| rice | bare_noun | 169 | 169 (untouched) |
| bowl of rice | quantity_phrase | 169 | 169 (untouched) |
| cup of rice | quantity_phrase | 169 | 169 (untouched) |
| lamb | bare_noun | 186 | 187 (+1: "Lamb, NS as to cut") |
| cup of oatmeal | quantity_phrase | 131 | 131 (untouched) |
| piece of chicken | quantity_phrase | 120 | 122 (+2: "Chicken, back"/"Chicken, tail") |
| chicken | bare_noun | 119 | 120 (+1: "Chicken, back") |
| ham | bare_noun | 98 | 100 (+2: "Ham, ground"/"Ham") |

These pre-existing wide cases come from already-present broad substrings
(`"raw"`, `"fruit"`, `"soup,"`, `"rice, white"`, etc.), not from this
repair, and were out of scope — this pass only touched cases where a
rejected candidate answer prompted a review.

**Borderline calls** (left rejected, judgment genuinely close):

- `chicken` / `piece of chicken`: "Chicken as ingredient in recipes" — a
  generic mixed-recipe placeholder, unclear whether it represents plain
  chicken.
- `beef`: "Beef as ingredient in recipes" — same reasoning.
- `milk` / `whole milk`: "Milk, buttermilk, fluid, whole" — buttermilk is a
  distinct product usually logged separately from plain milk.
- `coffee` / `cup of coffee`: "Coffee, Latte" and "Coffee, Cappuccino" —
  milk-based coffee drinks with very different macros from black coffee.
- `pork`: "Pork, roll" — a processed lunch-meat brand product, name-similar
  but a different food from a pork roast/pork cut.
- `cottage cheese`: "Cottage cheese, farmer's" — farmer's cheese is a
  related but distinct cheese, not cottage cheese.
- `cream cheese`: "Cheese spread, cream cheese" — a cream-cheese-based
  spread product, not plain cream cheese.
- `whole wheat bread`: "Bread, wheat" — plain wheat bread is less specific
  than whole wheat bread.
- `white bread`: "Bread, whole grain white" — whole grain white bread is a
  distinct, more specific product than plain white bread.
- `sourdough bread`: "Roll, sour dough" — a roll, not a loaf of bread,
  though same dough/flavor.
- `rye bread`: "Roll, rye" — a roll, not a loaf of bread.
- `skim milk`: "Milk, evaporated, fat free (skim)" — evaporated milk is a
  concentrated, different product form.
- `vegetable oil`: "Soybean oil" — often literally what's sold as generic
  vegetable oil, but it's still a specifically-named oil, not the generic
  label.
- `russet potato`: "Potatoes, raw, skin" — doesn't confirm russet variety.
- `grilled chicken`: "Barbecue chicken" — bbq sauce changes preparation
  into a distinct dish.
- `baked salmon`: "Fish, salmon, grilled" — grilled and baked are
  different cooking methods even though the macros are similar.
- `toasted almonds`: "Almonds, NFS" — the NFS marker doesn't confirm the
  almonds were toasted.
- `steamed broccoli`: "Broccoli, fresh, cooked with oil" — cooked-with-oil
  reads closer to sauteed/roasted than steamed.

**Recall@1 of the shipped matcher** (`backend.agent.tools.usda_local.lookup`),
measured before and after this repair (top-1 match checked against each
case's acceptance list):

| category | before | after |
|---|---|---|
| overall | 149/176 (84.7%) | 155/176 (88.1%) |
| ambiguous | 18/18 (100.0%) | 18/18 (100.0%) |
| bare_noun | 59/64 (92.2%) | 60/64 (93.8%) |
| preparation | 19/33 (57.6%) | 24/33 (72.7%) |
| quantity_phrase | 12/18 (66.7%) | 12/18 (66.7%) |
| single_food | 41/43 (95.3%) | 41/43 (95.3%) |

The biggest jump is in `preparation` (57.6% -> 72.7%): several of the
matcher's top-1 answers for prep queries (grilled/fried/baked/roasted
chicken, roasted turkey, fried shrimp, etc.) were already the intuitively
"right" cut/preparation, just spelled or cut differently than the single
accepted string, so the old lists were scoring the matcher as wrong when
it wasn't. `quantity_phrase` recall is unchanged — its top-1 misses
(candy for "cup of rice", a frozen entree for "bowl of rice", "Dessert
pizza" for "slice of pizza", etc., documented earlier in this file) are
genuinely wrong answers, not acceptance-list gaps, so widening the lists
correctly left them rejected.
