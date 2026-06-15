import asyncio
import os
import random
import uuid
from datetime import datetime, time, timedelta, timezone, date
from sqlalchemy import text as sa_text
import json

from dotenv import load_dotenv
load_dotenv()

from backend.db.session import get_session, dispose_engine
from backend.db.redis_client import reset_day_key
from backend.db.models import UserGoal

TARGET_USER_ID = "00000000-0000-0000-0000-000000000000"

# Meal templates: (meal_type, kcal, protein_g, carbs_g, fat_g, fiber_g, entities, flags)
TEMPLATES = [
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
        "kcal": 550.0,
        "protein_g": 38.0,
        "carbs_g": 45.0,
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
                "food_name": "Brown rice, cooked",
                "qty_g": 150.0,
                "kcal": 170.0,
                "protein_g": 4.0,
                "carbs_g": 35.0,
                "fat_g": 2.0,
                "fiber_g": 3.0,
            },
            {
                "food_name": "Mixed green salad with vinaigrette",
                "qty_g": 100.0,
                "kcal": 130.0,
                "protein_g": 2.0,
                "carbs_g": 10.0,
                "fat_g": 8.0,
                "fiber_g": 3.0,
            },
        ],
        "flags": {"has_junk": False, "junk_items": []},
    },
    {
        "meal_type": "dinner",
        "kcal": 650.0,
        "protein_g": 40.0,
        "carbs_g": 65.0,
        "fat_g": 18.0,
        "fiber_g": 8.0,
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
                "food_name": "Sweet potato, mashed",
                "qty_g": 200.0,
                "kcal": 230.0,
                "protein_g": 4.0,
                "carbs_g": 55.0,
                "fat_g": 2.0,
                "fiber_g": 6.0,
            },
            {
                "food_name": "Steamed broccoli",
                "qty_g": 150.0,
                "kcal": 100.0,
                "protein_g": 2.0,
                "carbs_g": 10.0,
                "fat_g": 2.0,
                "fiber_g": 2.0,
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
        "meal_type": "dinner",
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

async def main():
    rng = random.Random(42)
    session_factory = get_session()
    
    async with session_factory() as session:
        # 1. Clean up old data for TARGET_USER_ID
        print(f"Cleaning up existing meal logs and daily summaries for user {TARGET_USER_ID}...")
        await session.execute(
            sa_text("DELETE FROM meal_log WHERE user_id = :user_id"),
            {"user_id": TARGET_USER_ID}
        )
        await session.execute(
            sa_text("DELETE FROM daily_summary WHERE user_id = :user_id"),
            {"user_id": TARGET_USER_ID}
        )
        
        # 2. Check and ensure user_goal exists
        res = await session.execute(
            sa_text("SELECT user_id FROM user_goal WHERE user_id = :user_id"),
            {"user_id": TARGET_USER_ID}
        )
        row = res.fetchone()
        if not row:
            print(f"Creating default user_goal for user {TARGET_USER_ID}...")
            await session.execute(
                sa_text(
                    "INSERT INTO user_goal (user_id, kcal_goal, protein_goal, fiber_goal, dietary_prefs, streak_days) "
                    "VALUES (:user_id, 2000.0, 130.0, 25.0, '{}', 0)"
                ),
                {"user_id": TARGET_USER_ID}
            )
            
        # 3. Generate meals for the past 30 days
        today = datetime.now(timezone.utc).date()
        count = 0
        
        print("Seeding meals for the past 30 days...")
        # For each of the past 30 days, we'll add 2-3 meals to make it realistic
        for offset in range(30):
            day = today - timedelta(days=offset)
            # 2 to 3 meals per day
            n_meals = rng.randint(2, 4)
            meal_types = rng.sample(["breakfast", "lunch", "dinner", "snack"], k=n_meals)
            
            for meal_type in meal_types:
                # Find matching template or random choice
                matching = [t for t in TEMPLATES if t["meal_type"] == meal_type]
                template = rng.choice(matching) if matching else rng.choice(TEMPLATES)
                
                t = _random_time_for(meal_type, rng)
                logged_at = datetime.combine(day, t, tzinfo=timezone.utc)
                
                # Add a bit of randomness to template values
                var = rng.uniform(0.85, 1.15)
                kcal = template["kcal"] * var
                protein_g = template["protein_g"] * var
                carbs_g = template["carbs_g"] * var
                fat_g = template["fat_g"] * var
                fiber_g = template["fiber_g"] * var
                
                # Scale entities as well
                scaled_entities = []
                for ent in template["entities"]:
                    scaled_entities.append({
                        **ent,
                        "qty_g": ent["qty_g"] * var,
                        "kcal": ent["kcal"] * var,
                        "protein_g": ent["protein_g"] * var,
                        "carbs_g": ent["carbs_g"] * var,
                        "fat_g": ent.get("fat_g", 0.0) * var,
                        "fiber_g": ent.get("fiber_g", 0.0) * var,
                    })
                
                row_data = {
                    "meal_id": str(uuid.uuid4()),
                    "user_id": TARGET_USER_ID,
                    "logged_at": logged_at,
                    "meal_type": meal_type,
                    "kcal": kcal,
                    "protein_g": protein_g,
                    "carbs_g": carbs_g,
                    "fat_g": fat_g,
                    "fiber_g": fiber_g,
                    "entities": scaled_entities,
                    "flags": template["flags"],
                    "updated_at": logged_at,
                }
                
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
                        **row_data,
                        "entities": json.dumps(row_data["entities"]),
                        "flags": json.dumps(row_data["flags"]),
                    },
                )
                count += 1
                
        await session.commit()
        print(f"Successfully inserted {count} meals for user {TARGET_USER_ID}")
        
        # 4. Aggregate daily summaries for all 30 days
        print("Running daily summary aggregations...")
        from backend.workers.tasks import _aggregate_daily_summary
        for offset in range(30):
            day = today - timedelta(days=offset)
            await _aggregate_daily_summary(day)
            
        print("Daily summaries successfully updated.")
        
    # 5. Reset Redis cache key for target user
    print("Resetting Redis cache key...")
    try:
        await reset_day_key(TARGET_USER_ID)
        print("Redis cache key successfully reset.")
    except Exception as e:
        print(f"Note: Redis reset failed (maybe Redis is not running): {e}")
        
    await dispose_engine()

if __name__ == "__main__":
    asyncio.run(main())
