Break the described dish into its individual constituent ingredients with
realistic gram (or common-unit) amounts for the portion described.

Return an `ingredients` list where each entry is a single ingredient line a
person could have typed, formatted "<quantity> <food>", e.g.:
  - "150 g basmati rice"
  - "120 g chicken thigh"
  - "1 tbsp ghee"
  - "60 g onion"
  - "1 tsp garam masala"

Rules:
- Estimate amounts for ONE portion unless the description says otherwise
  (e.g. "biryani for two" → double).
- Include cooking fats/oils and notable condiments — they carry real
  calories.
- Use specific, USDA-searchable food names (e.g. "chicken thigh" not
  "chicken"; "basmati rice cooked" not "rice dish").
- If the input is already a single simple food (e.g. "an apple"), return it
  as the sole ingredient.
- Return an empty list only if the input is not food.
