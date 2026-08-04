"""embed_meal_summary keeps the dish word by embedding meal_log.label."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from backend.workers.tasks import _embed_meal_summary


def _meal(label, entities) -> SimpleNamespace:
    return SimpleNamespace(meal_type="dinner", label=label, entities=entities,
                           embedding=None)


async def _run_with(meal):
    session = MagicMock()
    session.get = AsyncMock(return_value=meal)
    session.commit = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    captured = {}

    async def fake_embed(text: str):
        captured["text"] = text
        return [0.0] * 768

    with patch("backend.workers.tasks.get_session", return_value=lambda: ctx), \
         patch("backend.workers.tasks.embed_text", side_effect=fake_embed):
        await _embed_meal_summary("meal-1")
    return captured["text"]


async def test_uses_label_when_present() -> None:
    meal = _meal("chicken biryani, apple",
                 [{"food_name": "basmati rice cooked"}, {"food_name": "apple raw"}])
    text = await _run_with(meal)
    assert "chicken biryani" in text and text.startswith("dinner:")


async def test_falls_back_to_food_names_when_label_none() -> None:
    meal = _meal(None, [{"food_name": "apple raw"}, {"food_name": "banana raw"}])
    text = await _run_with(meal)
    assert "apple raw" in text and "banana raw" in text
