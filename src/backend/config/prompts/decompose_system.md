Break the described dish into its individual constituent ingredients with
realistic amounts for the portion described.

Return an `ingredients` list. Each entry has:
  - `food_name`: a specific, USDA-searchable ingredient name
    (e.g. "chicken thigh" not "chicken"; "basmati rice cooked" not "rice dish").
  - `qty_g`: the ingredient's weight for the portion, IN GRAMS. Convert common
    cooking units to grams yourself (e.g. 1 tbsp oil ≈ 14 g, 1 tsp spice ≈ 3 g,
    1 cup cooked rice ≈ 160 g, 1 medium onion ≈ 110 g).
  - `unit`: the natural unit the ingredient was measured in ("g" if you thought
    in grams, otherwise "tbsp", "tsp", "cup", "piece", …).

Example — "chicken biryani for one":
  - {food_name: "basmati rice cooked", qty_g: 180, unit: "cup"}
  - {food_name: "chicken thigh", qty_g: 120, unit: "g"}
  - {food_name: "ghee", qty_g: 14, unit: "tbsp"}
  - {food_name: "onion", qty_g: 60, unit: "g"}
  - {food_name: "garam masala", qty_g: 3, unit: "tsp"}

Rules:
- Estimate amounts for ONE portion unless the description says otherwise
  (e.g. "biryani for two" → double every gram weight).
- Include cooking fats/oils and notable condiments — they carry real calories.
- If the input is already a single simple food (e.g. "an apple"), return it
  as the sole ingredient with its gram weight.
- Every `qty_g` must be a positive number of grams.
- Return an empty list only if the input is not food.
