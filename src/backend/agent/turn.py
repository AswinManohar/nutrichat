"""The response shape every chat turn returns."""

from __future__ import annotations

from typing import Any


def turn_response(
    message: str, *, paused: bool = False, **extra: Any
) -> dict[str, Any]:
    """The response shape every turn returns to the API and Telegram."""
    return {
        "status": "success",
        "message": message,
        "paused": paused,
        "items": [],
        **extra,
    }
