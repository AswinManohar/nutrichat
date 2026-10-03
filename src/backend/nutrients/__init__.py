"""Fixed micronutrient set (spec 008).

One catalogue (``config/nutrients.yaml``) defines every tracked nutrient;
this package holds the only implementations of the rules built on it:
catalogue lookups (``catalog``), per-item resolution and the meal summary
(``resolve``), and per-day totals (``daily``).
"""
