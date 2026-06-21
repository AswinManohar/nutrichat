Extract the time range, nutrients, and intent from this nutrition question.
time_range: today | yesterday | this_week | last_7_days | this_month
  | last_30_days | last_90_days | last_month | custom
Guidance for choosing time_range:
  - "today" / "yesterday" / "this week" map directly.
  - "last week" / "past 7 days" -> last_7_days.
  - "this month" / "so far this month" -> this_month.
  - "last 30 days" / "past month" (ambiguous, ~30 days) -> last_30_days.
  - "last month" (the previous calendar month) -> last_month.
  - "past two months" / "last 2 months" -> use custom with date_from set
    to 60 days before today and date_to set to today (ISO dates), or use
    last_30_days if you are unsure of the exact span.
  - If the question gives no time signal at all (e.g. "what do I eat
    the most?", "what's the unhealthiest food I eat?"), default to
    last_30_days.
IMPORTANT: if you choose "custom", you MUST always set both date_from
AND date_to as ISO dates (YYYY-MM-DD). Never choose "custom" without
filling in both dates — for any multi-week or multi-month phrase, either
pick one of the named ranges above or provide explicit custom bounds.
nutrients: extract EVERY nutrient asked for. For macros use aliases (kcal/protein_g/carbs_g/fat_g/fiber_g). For micros use EXACT USDA names (e.g. "Total Sugars" for sugar, "Iron, Fe" for iron, "Vitamin B-12", "Vitamin D (D2 + D3)", "Water"). If multiple are asked, list all.
include_goals: true if the user asks about goals or targets.
include_foods: true if the question is about WHAT foods were eaten —
  e.g. most/least frequent foods, what they eat the most/often,
  healthiest/unhealthiest foods, junk food, highest-calorie items, or
  any "what kind of food..." question. Otherwise false.

Special cases for time_range and flags when the question gives NO
explicit period:
  - "Most often" / "most frequent" / "favorite foods" / "what do I
    usually eat" questions with no explicit period -> time_range=
    "last_90_days" (a wider window better reflects habits) AND
    include_foods=true.
  - Other food-content questions (healthiest/unhealthiest/junk food,
    highest-calorie items) with no explicit period ->
    time_range="last_30_days" AND include_foods=true.
  - Holistic assessment/advice questions ("is my diet balanced", "what
    one change would improve my nutrition", "am I eating healthy", "am I
    eating too much junk", "what should I cut back on", "how am I
    doing") with no explicit period -> time_range="last_30_days" AND
    include_foods=true AND include_goals=true.
  - "Am I eating enough <macro/nutrient>" questions -> include_goals=true;
    if no period is given, default time_range="last_7_days".
  - Meal-suggestion / "what should I eat" questions — e.g. "what should
    I eat (to hit my goals / for dinner / next)", "plan my remaining
    meals", "I'm behind on X, what should I eat to catch up", "what
    should I have for breakfast/lunch/dinner", "give me a meal plan to
    meet my goals", "I have N calories left, suggest a meal" -> ALWAYS
    time_range="today" AND include_goals=true, regardless of any other
    period language in the question (so today's remaining totals can be
    computed against the daily goals).
