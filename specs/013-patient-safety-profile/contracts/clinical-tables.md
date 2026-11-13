# Contract: Clinical data files

Location: `src/backend/config/clinical/`. Every file is YAML, validated by a
Pydantic model at load (`extra="forbid"`). A file that fails validation is
treated as unreadable: the checker refuses recipes (none shown), and for
`red_flags.yaml` the screen fails closed (FR-017). The loader keeps a
SHA-256 content hash per file as its version, stored with every check and
escalation, and re-reads a file when its mtime changes (FR-013).

Common header on every file:

```yaml
version: 3                 # bumped by the editor, informational
reviewed_by: "Dietitian name or role"
reviewed_on: 2026-11-20
```

## allergen_groups.yaml

```yaml
groups:
  peanut:
    label: "peanut"
    terms: ["peanut", "peanuts", "groundnut", "peanut oil", "peanut butter", "arachis oil", "satay"]
    exclude_terms: []
  tree_nut:
    label: "tree nuts"
    terms: ["almond", "cashew", "walnut", "pecan", "pistachio", "hazelnut", "macadamia", "praline", "marzipan"]
    exclude_terms: ["nutmeg", "butternut", "water chestnut"]
  milk:
    label: "milk"
    terms: ["milk", "cheese", "butter", "ghee", "paneer", "yogurt", "curd", "whey", "casein", "cream"]
    exclude_terms: ["cocoa butter", "coconut milk", "almond milk", "oat milk", "soy milk"]
  # egg, fish, shellfish, soy, wheat_gluten, sesame, mustard, celery, lupin, sulphites ...
```

Matching: case-folded, word-boundary, longest term wins; applied to the
ingredient name and its USDA description (R8). `custom_terms` on an allergy
entry are matched the same way.

## drug_food_interactions.yaml

```yaml
drugs:
  warfarin:
    names: ["warfarin", "coumadin", "jantoven"]
    rules:
      - kind: nutrient_ceiling
        nutrient: vitamin_k
        amount: 90          # per meal; value set by the reviewing dietitian
        unit: mcg
        reason: "vitamin K changes how warfarin works"
  maoi:
    names: ["phenelzine", "tranylcypromine", "isocarboxazid", "selegiline"]
    rules:
      - kind: avoid_terms
        terms: ["aged cheese", "parmesan", "blue cheese", "soy sauce", "miso", "salami", "sauerkraut", "tap beer"]
        reason: "tyramine-rich foods can raise blood pressure with MAOIs"
  simvastatin:
    names: ["simvastatin", "zocor"]
    rules:
      - kind: avoid_terms
        terms: ["grapefruit", "pomelo"]
        reason: "grapefruit raises statin levels"
```

The values above are placeholders to be set by the reviewing dietitian before
PR 2 ships. A confirmed medication with no matching `names` produces a
`unknown_medication` review item and a "no known rule" note.

## diet_rules.yaml (FR-014)

```yaml
term_groups:                 # families not in allergen_groups.yaml
  meat:    { label: "meat", terms: ["beef", "pork", "..."], exclude_terms: [] }
  poultry: { label: "poultry", terms: ["chicken", "turkey", "..."], exclude_terms: [] }
settings:                    # keys are the diet chips
  vegan:       { groups: ["meat", "poultry", "fish", "shellfish", "egg", "milk"], terms: ["honey", "gelatin"] }
  vegetarian:  { groups: ["meat", "poultry", "fish", "shellfish"], terms: ["gelatin"] }
  pescatarian: { groups: ["meat", "poultry"], terms: [] }
  gluten_free: { groups: ["wheat_gluten"], terms: [] }
  dairy_free:  { groups: ["milk"], terms: [] }
  no_nuts:     { groups: ["peanut", "tree_nut"], terms: [] }
  low_sodium:  { groups: [], terms: [] }   # also low_sugar, low_carb, high_protein, keto, paleo
```

A group names a `term_groups` family or an `allergen_groups.yaml` group; a
setting with no groups is a preference: recorded in `applied`, never a failure.
An unknown group name makes the tables invalid.

## texture_rules.yaml

```yaml
levels: ["liquid", "puree", "minced_moist", "soft_bite_sized", "regular"]   # ordered, strictest first
limitations:
  swallowing: { default_max: "minced_moist" }
  chewing:    { default_max: "soft_bite_sized" }
crunchy_or_dry_blocked_for: ["swallowing", "chewing"]
crunchy_terms: ["nuts", "crackers", "toast", "chips", "raw carrot", "granola", "popcorn", "crisp"]
```

An entry's own `max_texture` overrides `default_max`.

## physical_rules.yaml

```yaml
grip:
  blocked_equipment: ["cast-iron pan", "stand mixer", "mandoline", "pressure cooker", "rolling pin"]
  blocked_step_terms: ["knead", "grate", "mince by hand", "whisk vigorously", "julienne"]
standing_time:
  compare: active_minutes          # against the entry's max_active_minutes
```

## condition_limits.yaml (FR-033 abstention, not defaults)

```yaml
conditions:
  ckd:          { label: "chronic kidney disease", expects_limits: ["potassium", "phosphorus", "protein", "sodium", "fluid"] }
  hypertension: { label: "high blood pressure", expects_limits: ["sodium"] }
  diabetes:     { label: "diabetes", expects_limits: ["carbohydrate"] }
  prediabetes:  { label: "prediabetes", expects_limits: [] }
```

Lists which limits a condition *should* have. A missing one produces a
`missing_values` note and the coach says no limit has been set. No numeric
default exists anywhere in the file by design.

## red_flags.yaml (FR-015)

```yaml
fallback_unavailable_text: "I can't reply right now. If this is urgent, contact your care team or emergency services."
rules:
  - id: stopped_insulin
    label: "Stopped insulin"
    patterns: ['\b(stopp?ed|quit|not taking|skipp(ing|ed))\b.{0,40}\binsulin\b', '\binsulin\b.{0,30}\b(stopped|quit)\b']
    response: "Stopping insulin can be dangerous. Please contact your doctor or diabetes team today. If you feel very unwell, drowsy, or are vomiting, seek emergency care now."
  - id: self_harm
    label: "Self-harm"
    patterns: ['...']
    response: "..."
```

Patterns are Python regexes compiled with `re.IGNORECASE`. The whole message is
searched; the first matching rule in file order wins. Fixed responses are
written and approved by the dietitians.
