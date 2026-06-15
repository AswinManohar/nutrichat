"""One-off script: seed realistic historical meal_log rows for a test user.

Run with:
    PYTHONPATH=src uv run python -m backend.scripts.seed_history

Inserts ~30 meal_log rows spread across the past ~60 days for the target
user, using a pool of realistic meal templates. Does not touch existing
rows (user_goal or any existing meal_log).
"""

from __future__ import annotations

import asyncio
import random
import uuid
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import text as sa_text

from backend.db.session import dispose_engine, get_session

TARGET_USER_ID = "5c3f42d5-4955-4ca6-acd2-3dcb0a043b6d"

# Meal templates: (meal_type, kcal, protein_g, carbs_g, fat_g, fiber_g, entities, flags)
TEMPLATES: list[dict] = [
    {
        "meal_type": "breakfast",
        "kcal": 350.0,
        "protein_g": 10.0,
        "carbs_g": 62.0,
        "fat_g": 7.0,
        "fiber_g": 7.0,
        "entities": [
            {
                "food_name": "Oatmeal, cooked",
                "qty_g": 240.0,
                "kcal": 250.0,
                "protein_g": 7.0,
                "carbs_g": 45.0,
                "fat_g": 5.0,
                "fiber_g": 5.0,
            },
            {
                "food_name": "Banana, raw",
                "qty_g": 120.0,
                "kcal": 100.0,
                "protein_g": 3.0,
                "carbs_g": 17.0,
                "fat_g": 2.0,
                "fiber_g": 2.0,
            },
        ],
        "flags": {"has_junk": False, "junk_items": []},
    },
    {
        "meal_type": "lunch",
        "kcal": 420.0,
        "protein_g": 38.0,
        "carbs_g": 18.0,
        "fat_g": 22.0,
        "fiber_g": 6.0,
        "entities": [
            {
                "food_name": "Chicken breast, grilled",
                "qty_g": 150.0,
                "kcal": 250.0,
                "protein_g": 32.0,
                "carbs_g": 0.0,
                "fat_g": 12.0,
                "fiber_g": 0.0,
            },
            {
                "food_name": "Mixed green salad with vinaigrette",
                "qty_g": 180.0,
                "kcal": 170.0,
                "protein_g": 6.0,
                "carbs_g": 18.0,
                "fat_g": 10.0,
                "fiber_g": 6.0,
            },
        ],
        "flags": {"has_junk": False, "junk_items": []},
    },
    {
        "meal_type": "dinner",
        "kcal": 550.0,
        "protein_g": 40.0,
        "carbs_g": 55.0,
        "fat_g": 16.0,
        "fiber_g": 4.0,
        "entities": [
            {
                "food_name": "Salmon, baked",
                "qty_g": 170.0,
                "kcal": 320.0,
                "protein_g": 34.0,
                "carbs_g": 0.0,
                "fat_g": 14.0,
                "fiber_g": 0.0,
            },
            {
                "food_name": "Rice, white, cooked",
                "qty_g": 200.0,
                "kcal": 230.0,
                "protein_g": 6.0,
                "carbs_g": 55.0,
                "fat_g": 2.0,
                "fiber_g": 4.0,
            },
        ],
        "flags": {"has_junk": False, "junk_items": []},
    },
    {
        "meal_type": "snack",
        "kcal": 180.0,
        "protein_g": 18.0,
        "carbs_g": 20.0,
        "fat_g": 3.0,
        "fiber_g": 3.0,
        "entities": [
            {
                "food_name": "Greek yogurt, plain, nonfat",
                "qty_g": 170.0,
                "kcal": 100.0,
                "protein_g": 17.0,
                "carbs_g": 6.0,
                "fat_g": 0.0,
                "fiber_g": 0.0,
            },
            {
                "food_name": "Mixed berries",
                "qty_g": 100.0,
                "kcal": 80.0,
                "protein_g": 1.0,
                "carbs_g": 14.0,
                "fat_g": 3.0,
                "fiber_g": 3.0,
            },
        ],
        "flags": {"has_junk": False, "junk_items": []},
    },
    {
        "meal_type": "breakfast",
        "kcal": 300.0,
        "protein_g": 18.0,
        "carbs_g": 28.0,
        "fat_g": 13.0,
        "fiber_g": 3.0,
        "entities": [
            {
                "food_name": "Eggs, scrambled",
                "qty_g": 120.0,
                "kcal": 180.0,
                "protein_g": 14.0,
                "carbs_g": 2.0,
                "fat_g": 12.0,
                "fiber_g": 0.0,
            },
            {
                "food_name": "Whole wheat toast",
                "qty_g": 60.0,
                "kcal": 120.0,
                "protein_g": 4.0,
                "carbs_g": 26.0,
                "fat_g": 1.0,
                "fiber_g": 3.0,
            },
        ],
        "flags": {"has_junk": False, "junk_items": []},
    },
    {
        "meal_type": "dinner",
        "kcal": 650.0,
        "protein_g": 30.0,
        "carbs_g": 75.0,
        "fat_g": 24.0,
        "fiber_g": 5.0,
        "entities": [
            {
                "food_name": "Pasta, cooked",
                "qty_g": 220.0,
                "kcal": 330.0,
                "protein_g": 12.0,
                "carbs_g": 65.0,
                "fat_g": 2.0,
                "fiber_g": 4.0,
            },
            {
                "food_name": "Beef bolognese sauce",
                "qty_g": 250.0,
                "kcal": 320.0,
                "protein_g": 18.0,
                "carbs_g": 10.0,
                "fat_g": 22.0,
                "fiber_g": 1.0,
            },
        ],
        "flags": {"has_junk": False, "junk_items": []},
    },
    {
        "meal_type": "snack",
        "kcal": 200.0,
        "protein_g": 30.0,
        "carbs_g": 12.0,
        "fat_g": 3.0,
        "fiber_g": 1.0,
        "entities": [
            {
                "food_name": "Whey protein shake",
                "qty_g": 300.0,
                "kcal": 200.0,
                "protein_g": 30.0,
                "carbs_g": 12.0,
                "fat_g": 3.0,
                "fiber_g": 1.0,
            },
        ],
        "flags": {"has_junk": False, "junk_items": []},
    },
    {
        "meal_type": "lunch",
        "kcal": 850.0,
        "protein_g": 35.0,
        "carbs_g": 80.0,
        "fat_g": 45.0,
        "fiber_g": 4.0,
        "entities": [
            {
                "food_name": "Cheeseburger",
                "qty_g": 250.0,
                "kcal": 550.0,
                "protein_g": 28.0,
                "carbs_g": 40.0,
                "fat_g": 30.0,
                "fiber_g": 2.0,
            },
            {
                "food_name": "French fries",
                "qty_g": 150.0,
                "kcal": 300.0,
                "protein_g": 7.0,
                "carbs_g": 40.0,
                "fat_g": 15.0,
                "fiber_g": 2.0,
            },
        ],
        "flags": {"has_junk": True, "junk_items": ["Cheeseburger", "French fries"]},
    },
    {
        "meal_type": "dinner",
        "kcal": 500.0,
        "protein_g": 22.0,
        "carbs_g": 70.0,
        "fat_g": 14.0,
        "fiber_g": 12.0,
        "entities": [
            {
                "food_name": "Lentil curry",
                "qty_g": 280.0,
                "kcal": 280.0,
                "protein_g": 16.0,
                "carbs_g": 38.0,
                "fat_g": 8.0,
                "fiber_g": 10.0,
            },
            {
                "food_name": "Rice, white, cooked",
                "qty_g": 180.0,
                "kcal": 220.0,
                "protein_g": 6.0,
                "carbs_g": 32.0,
                "fat_g": 6.0,
                "fiber_g": 2.0,
            },
        ],
        "flags": {"has_junk": False, "junk_items": []},
    },
    {
        "meal_type": "lunch",
        "kcal": 700.0,
        "protein_g": 40.0,
        "carbs_g": 65.0,
        "fat_g": 28.0,
        "fiber_g": 8.0,
        "entities": [
            {
                "food_name": "Chicken burrito",
                "qty_g": 400.0,
                "kcal": 700.0,
                "protein_g": 40.0,
                "carbs_g": 65.0,
                "fat_g": 28.0,
                "fiber_g": 8.0,
            },
        ],
        "flags": {"has_junk": False, "junk_items": []},
    },
]

MEAL_HOURS = {
    "breakfast": (7, 9),
    "lunch": (12, 14),
    "dinner": (18, 20),
    "snack": (15, 17),
}


def _random_time_for(meal_type: str, rng: random.Random) -> time:
    lo, hi = MEAL_HOURS[meal_type]
    hour = rng.randint(lo, hi)
    minute = rng.choice([0, 10, 15, 20, 30, 45])
    return time(hour=hour, minute=minute)


async def seed() -> int:
    """Insert ~30 historical meal_log rows for TARGET_USER_ID.

    Returns:
        Number of rows inserted.
    """
    rng = random.Random(42)
    today = datetime.now(timezone.utc).date()

    # Pick ~22 distinct days in the past 60 days (excluding today), then
    # assign 1-3 meals per day to reach ~30 rows total.
    candidate_days = list(range(1, 60))
    rng.shuffle(candidate_days)
    chosen_offsets = sorted(candidate_days[:22], reverse=True)

    rows: list[dict] = []
    for i, offset in enumerate(chosen_offsets):
        day = today - timedelta(days=offset)
        # First 8 days get 2-3 meals, rest get 1, to land near ~30 rows.
        if i < 5:
            n_meals = 3
        elif i < 10:
            n_meals = 2
        else:
            n_meals = 1

        meal_types_today = rng.sample(
            ["breakfast", "lunch", "dinner", "snack"], k=min(n_meals, 4)
        )

        for meal_type in meal_types_today:
            template = rng.choice(
                [t for t in TEMPLATES if t["meal_type"] == meal_type]
            )
            t = _random_time_for(meal_type, rng)
            logged_at = datetime.combine(day, t, tzinfo=timezone.utc)
            rows.append(
                {
                    "meal_id": str(uuid.uuid4()),
                    "user_id": TARGET_USER_ID,
                    "logged_at": logged_at,
                    "meal_type": template["meal_type"],
                    "kcal": template["kcal"],
                    "protein_g": template["protein_g"],
                    "carbs_g": template["carbs_g"],
                    "fat_g": template["fat_g"],
                    "fiber_g": template["fiber_g"],
                    "entities": template["entities"],
                    "flags": template["flags"],
                    "updated_at": logged_at,
                }
            )

    session_factory = get_session()
    async with session_factory() as session:
        for row in rows:
            await session.execute(
                sa_text(
                    "INSERT INTO meal_log "
                    "(meal_id, user_id, logged_at, meal_type, kcal, protein_g, "
                    "carbs_g, fat_g, fiber_g, entities, flags, updated_at) "
                    "VALUES (:meal_id, :user_id, :logged_at, :meal_type, :kcal, "
                    ":protein_g, :carbs_g, :fat_g, :fiber_g, "
                    "CAST(:entities AS jsonb), CAST(:flags AS jsonb), :updated_at)"
                ),
                {
                    **row,
                    "entities": __import__("json").dumps(row["entities"]),
                    "flags": __import__("json").dumps(row["flags"]),
                },
            )
        await session.commit()

    await dispose_engine()
    return len(rows)


if __name__ == "__main__":
    n = asyncio.run(seed())
    print(f"Inserted {n} meal_log rows for user {TARGET_USER_ID}")
