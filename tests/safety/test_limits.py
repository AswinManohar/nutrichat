"""Today's progress against nutrient limits, derived from meal_log."""

from __future__ import annotations

from datetime import timedelta

from backend.core.nutrition_day import current_day_bounds
from backend.db.models import MealLog
from backend.db.session import get_session
from backend.safety import profile
from backend.safety.limits import limits_today
from backend.safety.profile import NutrientLimitValue


def _item(sodium_mg: float | None, protein_g: float | None = 1.0) -> dict:
    nutrients = (
        {} if sodium_mg is None else {"Sodium, Na": {"amount": sodium_mg, "unit": "mg"}}
    )
    return {
        "food_name": "x",
        "qty_g": 100,
        "protein_g": protein_g,
        "nutrients": nutrients,
    }


async def _log(user_id: str, items: list[dict], *, deleted: bool = False, days_ago=0):
    start, _ = current_day_bounds()
    async with get_session()() as session:
        session.add(
            MealLog(
                user_id=user_id,
                logged_at=start + timedelta(hours=1) - timedelta(days=days_ago),
                meal_type="lunch",
                kcal=100,
                protein_g=1,
                carbs_g=1,
                fat_g=1,
                fiber_g=1,
                entities=items,
                deleted_at=start if deleted else None,
            )
        )
        await session.commit()


async def _limit(user_id: str, **kwargs):
    return await profile.add_entry(
        user_id,
        NutrientLimitValue(**kwargs),
        source="patient",
        state="confirmed",
        created_by="patient",
    )


async def test_per_day_limit_sums_today_and_flags_unknown_items(db_user) -> None:
    await _limit(db_user, nutrient="sodium", amount=1500, unit="mg", period="per_day")
    await _log(db_user, [_item(600), _item(None)])
    await _log(db_user, [_item(320)])
    await _log(db_user, [_item(9000)], deleted=True)
    await _log(db_user, [_item(9000)], days_ago=1)

    result = await limits_today(db_user)

    assert (result.on_track, result.total) == (1, 1)
    (sodium,) = result.limits
    assert (sodium.so_far, sodium.unknown_items, sodium.on_track) == (920, 1, True)
    assert sodium.label == "Up to 1,500 mg a day"
    assert sodium.period == "per_day" and sodium.min_amount is None


async def test_going_over_the_ceiling_is_not_on_track(db_user) -> None:
    await _limit(db_user, nutrient="sodium", amount=1000, unit="mg", period="per_day")
    await _log(db_user, [_item(700)])
    await _log(db_user, [_item(400)])

    result = await limits_today(db_user)

    assert (result.on_track, result.total) == (0, 1)
    assert result.limits[0].so_far == 1100 and not result.limits[0].on_track


async def test_per_meal_limit_reports_the_highest_single_meal(db_user) -> None:
    await _limit(db_user, nutrient="sodium", amount=800, unit="mg", period="per_meal")
    await _log(db_user, [_item(300), _item(300)])
    await _log(db_user, [_item(500)])

    (sodium,) = (await limits_today(db_user)).limits

    assert sodium.so_far == 600 and sodium.on_track


async def test_macro_limits_read_the_item_fields_and_convert_units(db_user) -> None:
    await _limit(
        db_user,
        nutrient="protein",
        amount=60,
        min_amount=50,
        unit="g",
        period="per_day",
    )
    await _limit(db_user, nutrient="sodium", amount=2, unit="g", period="per_day")
    await _log(db_user, [_item(1500, protein_g=40), _item(500, protein_g=None)])

    by_nutrient = {p.nutrient: p for p in (await limits_today(db_user)).limits}

    assert by_nutrient["protein"].so_far == 40
    assert by_nutrient["protein"].unknown_items == 1
    assert by_nutrient["protein"].label == "50-60 g a day"
    assert by_nutrient["sodium"].so_far == 2.0 and by_nutrient["sodium"].on_track


async def test_no_limits_means_an_empty_answer(db_user) -> None:
    result = await limits_today(db_user)

    assert (result.on_track, result.total, result.limits) == (0, 0, [])


async def test_pending_limits_are_not_reported(db_user) -> None:
    await profile.add_entry(
        db_user,
        NutrientLimitValue(nutrient="sodium", amount=1, unit="g", period="per_day"),
        source="inferred",
        state="pending",
        created_by="curator",
    )

    assert (await limits_today(db_user)).total == 0
