"""One-off script: simulate 5 synthetic users with distinct eating patterns,
run the coaching agent's food-reasoning questions against each, and clean up
afterward.

Run with:
    set -a; . ./.env; set +a
    PYTHONPATH=src .venv/bin/python -m backend.scripts.simulate_coaching_users

Creates user_goal + ~30 meal_log rows (spread over the past ~60 days) for
five throwaway UUIDs (000...ef01 .. 000...ef05), asks CoachingAgent four
food-reasoning questions per user, prints the answers, then deletes all
rows for those five users. Never touches any other user's data.
"""

from __future__ import annotations

import asyncio
import json
import random
import uuid
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import text as sa_text

from backend.agent.coaching import CoachingAgent
from backend.db.session import dispose_engine, get_session

SYNTHETIC_USER_IDS = [
    "00000000-0000-0000-0000-0000000aef01",
    "00000000-0000-0000-0000-0000000aef02",
    "00000000-0000-0000-0000-0000000aef03",
    "00000000-0000-0000-0000-0000000aef04",
    "00000000-0000-0000-0000-0000000aef05",
]

GOALS = {
    SYNTHETIC_USER_IDS[0]: {"kcal_goal": 2200.0, "protein_goal": 160.0, "fiber_goal": 30.0},
    SYNTHETIC_USER_IDS[1]: {"kcal_goal": 2500.0, "protein_goal": 120.0, "fiber_goal": 25.0},
    SYNTHETIC_USER_IDS[2]: {"kcal_goal": 1900.0, "protein_goal": 100.0, "fiber_goal": 35.0},
    SYNTHETIC_USER_IDS[3]: {"kcal_goal": 2400.0, "protein_goal": 110.0, "fiber_goal": 28.0},
    SYNTHETIC_USER_IDS[4]: {"kcal_goal": 2100.0, "protein_goal": 130.0, "fiber_goal": 30.0},
}

# Per-user pools of meal templates: (meal_type, kcal, protein_g, carbs_g,
# fat_g, fiber_g, entities, flags). Each user gets a distinct "signature"
# food that dominates their frequency / junk / highest-calorie breakdowns.
USER_TEMPLATES: dict[str, list[dict]] = {
    # user1 — heavy on chicken salad + protein shakes (lean, high-protein)
    SYNTHETIC_USER_IDS[0]: [
        {
            "meal_type": "lunch",
            "kcal": 420.0, "protein_g": 42.0, "carbs_g": 14.0, "fat_g": 20.0, "fiber_g": 6.0,
            "entities": [
                {"food_name": "Chicken salad with greens", "qty_g": 320.0, "kcal": 420.0,
                 "protein_g": 42.0, "carbs_g": 14.0, "fat_g": 20.0, "fiber_g": 6.0},
            ],
            "flags": {"has_junk": False, "junk_items": []},
        },
        {
            "meal_type": "snack",
            "kcal": 180.0, "protein_g": 30.0, "carbs_g": 8.0, "fat_g": 2.0, "fiber_g": 0.0,
            "entities": [
                {"food_name": "Whey protein shake", "qty_g": 300.0, "kcal": 180.0,
                 "protein_g": 30.0, "carbs_g": 8.0, "fat_g": 2.0, "fiber_g": 0.0},
            ],
            "flags": {"has_junk": False, "junk_items": []},
        },
        {
            "meal_type": "breakfast",
            "kcal": 320.0, "protein_g": 22.0, "carbs_g": 30.0, "fat_g": 12.0, "fiber_g": 4.0,
            "entities": [
                {"food_name": "Eggs, scrambled", "qty_g": 150.0, "kcal": 220.0,
                 "protein_g": 18.0, "carbs_g": 2.0, "fat_g": 14.0, "fiber_g": 0.0},
                {"food_name": "Whole wheat toast", "qty_g": 60.0, "kcal": 100.0,
                 "protein_g": 4.0, "carbs_g": 28.0, "fat_g": 1.0, "fiber_g": 4.0},
            ],
            "flags": {"has_junk": False, "junk_items": []},
        },
        {
            "meal_type": "dinner",
            "kcal": 580.0, "protein_g": 48.0, "carbs_g": 45.0, "fat_g": 18.0, "fiber_g": 6.0,
            "entities": [
                {"food_name": "Chicken salad with greens", "qty_g": 280.0, "kcal": 380.0,
                 "protein_g": 38.0, "carbs_g": 10.0, "fat_g": 16.0, "fiber_g": 5.0},
                {"food_name": "Rice, white, cooked", "qty_g": 180.0, "kcal": 200.0,
                 "protein_g": 10.0, "carbs_g": 35.0, "fat_g": 2.0, "fiber_g": 1.0},
            ],
            "flags": {"has_junk": False, "junk_items": []},
        },
    ],
    # user2 — frequent burgers/fries + pizza (junk-heavy)
    SYNTHETIC_USER_IDS[1]: [
        {
            "meal_type": "lunch",
            "kcal": 850.0, "protein_g": 35.0, "carbs_g": 80.0, "fat_g": 45.0, "fiber_g": 4.0,
            "entities": [
                {"food_name": "Cheeseburger", "qty_g": 250.0, "kcal": 550.0,
                 "protein_g": 28.0, "carbs_g": 40.0, "fat_g": 30.0, "fiber_g": 2.0},
                {"food_name": "French fries", "qty_g": 150.0, "kcal": 300.0,
                 "protein_g": 7.0, "carbs_g": 40.0, "fat_g": 15.0, "fiber_g": 2.0},
            ],
            "flags": {"has_junk": True, "junk_items": ["Cheeseburger", "French fries"]},
        },
        {
            "meal_type": "dinner",
            "kcal": 760.0, "protein_g": 30.0, "carbs_g": 90.0, "fat_g": 32.0, "fiber_g": 3.0,
            "entities": [
                {"food_name": "Pepperoni pizza", "qty_g": 260.0, "kcal": 760.0,
                 "protein_g": 30.0, "carbs_g": 90.0, "fat_g": 32.0, "fiber_g": 3.0},
            ],
            "flags": {"has_junk": True, "junk_items": ["Pepperoni pizza"]},
        },
        {
            "meal_type": "breakfast",
            "kcal": 310.0, "protein_g": 8.0, "carbs_g": 45.0, "fat_g": 12.0, "fiber_g": 2.0,
            "entities": [
                {"food_name": "Glazed donut", "qty_g": 70.0, "kcal": 310.0,
                 "protein_g": 8.0, "carbs_g": 45.0, "fat_g": 12.0, "fiber_g": 2.0,
                 "sugar_g": 22.0},
            ],
            "flags": {"has_junk": True, "junk_items": ["Glazed donut"]},
        },
        {
            "meal_type": "snack",
            "kcal": 250.0, "protein_g": 4.0, "carbs_g": 35.0, "fat_g": 10.0, "fiber_g": 1.0,
            "entities": [
                {"food_name": "Cola, regular", "qty_g": 355.0, "kcal": 150.0,
                 "protein_g": 0.0, "carbs_g": 39.0, "fat_g": 0.0, "fiber_g": 0.0,
                 "sugar_g": 39.0},
                {"food_name": "Potato chips", "qty_g": 50.0, "kcal": 100.0,
                 "protein_g": 4.0, "carbs_g": 10.0, "fat_g": 10.0, "fiber_g": 1.0},
            ],
            "flags": {"has_junk": True, "junk_items": ["Cola, regular", "Potato chips"]},
        },
    ],
    # user3 — oatmeal/yogurt/fruit (high fiber, healthy)
    SYNTHETIC_USER_IDS[2]: [
        {
            "meal_type": "breakfast",
            "kcal": 350.0, "protein_g": 10.0, "carbs_g": 62.0, "fat_g": 7.0, "fiber_g": 7.0,
            "entities": [
                {"food_name": "Oatmeal, cooked", "qty_g": 240.0, "kcal": 250.0,
                 "protein_g": 7.0, "carbs_g": 45.0, "fat_g": 5.0, "fiber_g": 5.0},
                {"food_name": "Banana, raw", "qty_g": 120.0, "kcal": 100.0,
                 "protein_g": 3.0, "carbs_g": 17.0, "fat_g": 2.0, "fiber_g": 2.0},
            ],
            "flags": {"has_junk": False, "junk_items": []},
        },
        {
            "meal_type": "snack",
            "kcal": 180.0, "protein_g": 18.0, "carbs_g": 20.0, "fat_g": 3.0, "fiber_g": 3.0,
            "entities": [
                {"food_name": "Greek yogurt, plain, nonfat", "qty_g": 170.0, "kcal": 100.0,
                 "protein_g": 17.0, "carbs_g": 6.0, "fat_g": 0.0, "fiber_g": 0.0},
                {"food_name": "Mixed berries", "qty_g": 100.0, "kcal": 80.0,
                 "protein_g": 1.0, "carbs_g": 14.0, "fat_g": 3.0, "fiber_g": 3.0},
            ],
            "flags": {"has_junk": False, "junk_items": []},
        },
        {
            "meal_type": "lunch",
            "kcal": 420.0, "protein_g": 22.0, "carbs_g": 55.0, "fat_g": 12.0, "fiber_g": 10.0,
            "entities": [
                {"food_name": "Lentil curry", "qty_g": 280.0, "kcal": 280.0,
                 "protein_g": 16.0, "carbs_g": 38.0, "fat_g": 8.0, "fiber_g": 10.0},
                {"food_name": "Mixed berries", "qty_g": 100.0, "kcal": 80.0,
                 "protein_g": 1.0, "carbs_g": 14.0, "fat_g": 3.0, "fiber_g": 3.0},
            ],
            "flags": {"has_junk": False, "junk_items": []},
        },
        {
            "meal_type": "dinner",
            "kcal": 480.0, "protein_g": 28.0, "carbs_g": 50.0, "fat_g": 14.0, "fiber_g": 8.0,
            "entities": [
                {"food_name": "Salmon, baked", "qty_g": 170.0, "kcal": 320.0,
                 "protein_g": 34.0, "carbs_g": 0.0, "fat_g": 14.0, "fiber_g": 0.0},
                {"food_name": "Oatmeal, cooked", "qty_g": 150.0, "kcal": 160.0,
                 "protein_g": 5.0, "carbs_g": 30.0, "fat_g": 3.0, "fiber_g": 4.0},
            ],
            "flags": {"has_junk": False, "junk_items": []},
        },
    ],
    # user4 — pasta/pizza heavy
    SYNTHETIC_USER_IDS[3]: [
        {
            "meal_type": "dinner",
            "kcal": 650.0, "protein_g": 30.0, "carbs_g": 75.0, "fat_g": 24.0, "fiber_g": 5.0,
            "entities": [
                {"food_name": "Pasta, cooked", "qty_g": 220.0, "kcal": 330.0,
                 "protein_g": 12.0, "carbs_g": 65.0, "fat_g": 2.0, "fiber_g": 4.0},
                {"food_name": "Beef bolognese sauce", "qty_g": 250.0, "kcal": 320.0,
                 "protein_g": 18.0, "carbs_g": 10.0, "fat_g": 22.0, "fiber_g": 1.0},
            ],
            "flags": {"has_junk": False, "junk_items": []},
        },
        {
            "meal_type": "lunch",
            "kcal": 760.0, "protein_g": 30.0, "carbs_g": 90.0, "fat_g": 32.0, "fiber_g": 3.0,
            "entities": [
                {"food_name": "Pepperoni pizza", "qty_g": 260.0, "kcal": 760.0,
                 "protein_g": 30.0, "carbs_g": 90.0, "fat_g": 32.0, "fiber_g": 3.0,
                 "sat_fat_g": 14.0},
            ],
            "flags": {"has_junk": True, "junk_items": ["Pepperoni pizza"]},
        },
        {
            "meal_type": "breakfast",
            "kcal": 300.0, "protein_g": 18.0, "carbs_g": 28.0, "fat_g": 13.0, "fiber_g": 3.0,
            "entities": [
                {"food_name": "Eggs, scrambled", "qty_g": 120.0, "kcal": 180.0,
                 "protein_g": 14.0, "carbs_g": 2.0, "fat_g": 12.0, "fiber_g": 0.0},
                {"food_name": "Whole wheat toast", "qty_g": 60.0, "kcal": 120.0,
                 "protein_g": 4.0, "carbs_g": 26.0, "fat_g": 1.0, "fiber_g": 3.0},
            ],
            "flags": {"has_junk": False, "junk_items": []},
        },
        {
            "meal_type": "dinner",
            "kcal": 700.0, "protein_g": 26.0, "carbs_g": 95.0, "fat_g": 22.0, "fiber_g": 5.0,
            "entities": [
                {"food_name": "Pasta, cooked", "qty_g": 250.0, "kcal": 375.0,
                 "protein_g": 14.0, "carbs_g": 74.0, "fat_g": 2.0, "fiber_g": 4.0},
                {"food_name": "Garlic bread", "qty_g": 100.0, "kcal": 325.0,
                 "protein_g": 12.0, "carbs_g": 21.0, "fat_g": 20.0, "fiber_g": 1.0,
                 "sat_fat_g": 10.0},
            ],
            "flags": {"has_junk": True, "junk_items": ["Garlic bread"]},
        },
    ],
    # user5 — mixed: some healthy, some junk, varied
    SYNTHETIC_USER_IDS[4]: [
        {
            "meal_type": "breakfast",
            "kcal": 320.0, "protein_g": 22.0, "carbs_g": 30.0, "fat_g": 12.0, "fiber_g": 4.0,
            "entities": [
                {"food_name": "Eggs, scrambled", "qty_g": 150.0, "kcal": 220.0,
                 "protein_g": 18.0, "carbs_g": 2.0, "fat_g": 14.0, "fiber_g": 0.0},
                {"food_name": "Whole wheat toast", "qty_g": 60.0, "kcal": 100.0,
                 "protein_g": 4.0, "carbs_g": 28.0, "fat_g": 1.0, "fiber_g": 4.0},
            ],
            "flags": {"has_junk": False, "junk_items": []},
        },
        {
            "meal_type": "lunch",
            "kcal": 700.0, "protein_g": 40.0, "carbs_g": 65.0, "fat_g": 28.0, "fiber_g": 8.0,
            "entities": [
                {"food_name": "Chicken burrito", "qty_g": 400.0, "kcal": 700.0,
                 "protein_g": 40.0, "carbs_g": 65.0, "fat_g": 28.0, "fiber_g": 8.0},
            ],
            "flags": {"has_junk": False, "junk_items": []},
        },
        {
            "meal_type": "dinner",
            "kcal": 850.0, "protein_g": 35.0, "carbs_g": 80.0, "fat_g": 45.0, "fiber_g": 4.0,
            "entities": [
                {"food_name": "Cheeseburger", "qty_g": 250.0, "kcal": 550.0,
                 "protein_g": 28.0, "carbs_g": 40.0, "fat_g": 30.0, "fiber_g": 2.0},
                {"food_name": "French fries", "qty_g": 150.0, "kcal": 300.0,
                 "protein_g": 7.0, "carbs_g": 40.0, "fat_g": 15.0, "fiber_g": 2.0},
            ],
            "flags": {"has_junk": True, "junk_items": ["Cheeseburger", "French fries"]},
        },
        {
            "meal_type": "snack",
            "kcal": 180.0, "protein_g": 18.0, "carbs_g": 20.0, "fat_g": 3.0, "fiber_g": 3.0,
            "entities": [
                {"food_name": "Greek yogurt, plain, nonfat", "qty_g": 170.0, "kcal": 100.0,
                 "protein_g": 17.0, "carbs_g": 6.0, "fat_g": 0.0, "fiber_g": 0.0},
                {"food_name": "Mixed berries", "qty_g": 100.0, "kcal": 80.0,
                 "protein_g": 1.0, "carbs_g": 14.0, "fat_g": 3.0, "fiber_g": 3.0},
            ],
            "flags": {"has_junk": False, "junk_items": []},
        },
    ],
}

MEAL_HOURS = {
    "breakfast": (7, 9),
    "lunch": (12, 14),
    "dinner": (18, 20),
    "snack": (15, 17),
}

QUESTIONS = [
    "what kind of food do I eat the most?",
    "what is the unhealthiest food I had?",
    "how much protein did I eat last week?",
    "how many calories on average over the last month?",
]


def _random_time_for(meal_type: str, rng: random.Random) -> time:
    lo, hi = MEAL_HOURS[meal_type]
    hour = rng.randint(lo, hi)
    minute = rng.choice([0, 10, 15, 20, 30, 45])
    return time(hour=hour, minute=minute)


def _build_rows(user_id: str, templates: list[dict], seed: int) -> list[dict]:
    """Build ~30 meal_log rows over the past ~60 days for one user."""
    rng = random.Random(seed)
    today = datetime.now(timezone.utc).date()

    candidate_days = list(range(1, 60))
    rng.shuffle(candidate_days)
    chosen_offsets = sorted(candidate_days[:22], reverse=True)

    rows: list[dict] = []
    for i, offset in enumerate(chosen_offsets):
        day = today - timedelta(days=offset)
        n_meals = 3 if i < 5 else (2 if i < 10 else 1)
        meal_types_today = rng.sample(
            ["breakfast", "lunch", "dinner", "snack"], k=min(n_meals, 4)
        )
        for meal_type in meal_types_today:
            pool = [t for t in templates if t["meal_type"] == meal_type]
            if not pool:
                continue
            template = rng.choice(pool)
            t = _random_time_for(meal_type, rng)
            logged_at = datetime.combine(day, t, tzinfo=timezone.utc)
            rows.append(
                {
                    "meal_id": str(uuid.uuid4()),
                    "user_id": user_id,
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
    return rows


def _with_item_micros(entities: list[dict]) -> list[dict]:
    """Move template sugar / sat-fat into each item's compact micros (spec 008).

    Items store micronutrients only as ``micros: {key: [amount, "u"|"e"]}``
    (data-model §2); template values are USDA-like, hence "u".
    """
    out: list[dict] = []
    for ent in entities:
        pairs = (("sugar_g", "total_sugars"), ("sat_fat_g", "saturated_fat"))
        micros = {
            key: [float(ent[field]), "u"]
            for field, key in pairs
            if ent.get(field) is not None
        }
        rest = {k: v for k, v in ent.items() if k not in ("sugar_g", "sat_fat_g")}
        out.append({**rest, "micros": micros})
    return out


async def seed_users() -> None:
    """Insert user_goal + meal_log rows for the 5 synthetic users."""
    session_factory = get_session()
    async with session_factory() as session:
        for i, user_id in enumerate(SYNTHETIC_USER_IDS, start=1):
            goal = GOALS[user_id]
            await session.execute(
                sa_text(
                    "INSERT INTO user_goal "
                    "(user_id, kcal_goal, protein_goal, fiber_goal, dietary_prefs) "
                    "VALUES (:user_id, :kcal_goal, :protein_goal, :fiber_goal, "
                    "CAST(:dietary_prefs AS jsonb))"
                ),
                {
                    "user_id": user_id,
                    "dietary_prefs": json.dumps({}),
                    **goal,
                },
            )
            rows = _build_rows(user_id, USER_TEMPLATES[user_id], seed=100 + i)
            for row in rows:
                entities = _with_item_micros(row["entities"])
                await session.execute(
                    sa_text(
                        "INSERT INTO meal_log "
                        "(meal_id, user_id, logged_at, meal_type, kcal, protein_g, "
                        "carbs_g, fat_g, fiber_g, entities, flags, updated_at) "
                        "VALUES (:meal_id, :user_id, :logged_at, :meal_type, :kcal, "
                        ":protein_g, :carbs_g, :fat_g, :fiber_g, "
                        "CAST(:entities AS jsonb), CAST(:flags AS jsonb), "
                        ":updated_at)"
                    ),
                    {
                        **row,
                        "entities": json.dumps(entities),
                        "flags": json.dumps(row["flags"]),
                    },
                )
            print(f"Seeded {len(rows)} meal_log rows for {user_id}")
        await session.commit()


async def run_simulations() -> None:
    """Run the four coaching questions for each synthetic user."""
    agent = CoachingAgent()
    for user_id in SYNTHETIC_USER_IDS:
        print(f"\n=== {user_id} ===")
        for question in QUESTIONS:
            answer = await agent.handle(user_id, question)
            print(f"Q: {question}\nA: {answer.message}\n")


async def cleanup_users() -> None:
    """Delete meal_log + user_goal rows for the 5 synthetic users."""
    session_factory = get_session()
    async with session_factory() as session:
        for user_id in SYNTHETIC_USER_IDS:
            await session.execute(
                sa_text("DELETE FROM meal_log WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
            await session.execute(
                sa_text("DELETE FROM user_goal WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
        await session.commit()
    print("Cleaned up synthetic users.")


async def main() -> None:
    await seed_users()
    await run_simulations()
    await cleanup_users()
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
