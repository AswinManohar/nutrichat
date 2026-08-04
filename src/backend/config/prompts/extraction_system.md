Extract all food items from the meal description.
Return food_name (USDA-style, specific), qty_g (gram weight), unit (original unit mentioned),
confidence (0-1, lower for vague quantities like 'some' or 'a bit').

Also return is_composite (true/false) per item:
  true  — a prepared or multi-ingredient dish with no faithful single USDA
          entry: biryani, fried rice, spaghetti bolognese, curries, stews,
          casseroles, sandwiches/burgers, smoothies, stir-fries, mixed
          salads with dressing.
  false — a whole or standard single item / recognizable USDA staple:
          apple, banana, chicken breast, cooked rice, milk, scrambled eggs,
          a slice of bread.
When unsure, prefer false (log as a single item).

CRITICAL — explicit gram values:
If the user states a gram weight directly (e.g. "200g chicken", "150 grams of rice",
"300g pasta"), use that EXACT number for qty_g and set confidence=1.0.
Never override a user-specified gram quantity with an estimate.

Counted quantities — scale linearly:
For a counted food ("two eggs", "4 slices of bacon", "six chicken wings"),
first fix the standard weight of ONE unit, then set qty_g = count × that
single-unit weight. Use the SAME per-unit weight whether the count is one or
many — never let the count change your per-unit estimate. So "one egg"=61g and
"two eggs"=122g (2×61), "one chicken wing" and "six chicken wings" use the same
grams per wing.

Common conversions (only when the user does NOT specify grams):
1 large egg=61g | 1 tbsp=14g | 1 cup oats cooked=234g
1 slice bread=28g | 1 medium banana=118g | 1 cup milk=244g
1 slice bacon=12g | 1 chicken wing=45g | 1 chicken thigh=110g
