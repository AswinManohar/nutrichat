"""Client for Fastino GLiDE, the model behind every typed judgment.

GLiDE answers fixed questions about a piece of state with calibrated
probabilities instead of generated text. One request carries one ``state``
and any number of named questions; the answers come back under the same
names (``POST /v1/systemone``, see docs.fastino.ai/inference/systemone).

Two callers: agent/system_one.py (routing, on the reply path) and
agent/memory_judge.py (memory save decision, in Celery). Each owns its
``httpx`` client because their timeouts and event loops differ; this module
owns the request and response format.

Nothing here logs or raises with the request or response body: failures
surface as :class:`GlideUnavailable` carrying a short reason only.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from backend.config import get_tunables

_CONFIG = get_tunables().glide
API_KEY_ENV = "FASTINO_API_KEY"
_PATH = "/v1/systemone"

Question = dict[str, Any]
Questions = dict[str, Question]


class GlideUnavailable(Exception):
    """GLiDE gave no usable answer.

    ``reason`` is safe to log and record: ``timeout``, ``http_<status>``,
    ``malformed_response``, or a transport exception's class name.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class GlideResponse(BaseModel):
    """The parts of a System One response the backend reads."""

    answers: dict[str, dict[str, Any]]
    model: str
    input_tokens: int = Field(ge=0)

    model_config = ConfigDict(extra="forbid")

    def noul(self, key: str) -> float:
        """Return P(true) for a yes/no question.

        Raises:
            GlideUnavailable: The answer is missing or not a probability.
        """
        try:
            value = float(self.answers[key]["noul"])
        except (KeyError, TypeError, ValueError):
            raise GlideUnavailable("malformed_response") from None
        if not 0.0 <= value <= 1.0:
            raise GlideUnavailable("malformed_response")
        return value

    def choice(self, key: str) -> tuple[str, dict[str, float]]:
        """Return the winning option and every option's probability.

        Raises:
            GlideUnavailable: The answer is missing or misshapen.
        """
        try:
            answer = self.answers[key]
            probabilities = {
                str(k): float(v) for k, v in answer["probabilities"].items()
            }
            return str(answer["choice"]), probabilities
        except (KeyError, TypeError, ValueError, AttributeError):
            raise GlideUnavailable("malformed_response") from None


def noul(instructions: str, criteria: dict[str, str] | None = None) -> Question:
    """Build a yes/no question; ``criteria`` describes "true" and "false"."""
    question: Question = {"type": "noul", "instructions": instructions}
    if criteria is not None:
        question["criteria"] = criteria
    return question


def choice(instructions: str, criteria: dict[str, Any]) -> Question:
    """Build a pick-one question; ``criteria`` maps each option to its meaning."""
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def api_key() -> str:
    """Return the configured API key, or an empty string."""
    return os.environ.get(API_KEY_ENV, "")


def make_client(timeout_s: float, **kwargs: Any) -> httpx.AsyncClient | None:
    """Return an ``httpx`` client for GLiDE, or None when no key is set.

    Args:
        timeout_s: Default per-request timeout.
        **kwargs: Passed to ``httpx.AsyncClient`` (for example ``limits``).
    """
    key = api_key()
    if not key:
        return None
    return httpx.AsyncClient(
        base_url=_CONFIG.base_url,
        headers={"X-API-Key": key},
        timeout=timeout_s,
        **kwargs,
    )


async def ask(
    client: httpx.AsyncClient,
    state: dict[str, str],
    questions: Questions,
    *,
    timeout_s: float | None = None,
) -> GlideResponse:
    """Send one System One request. One attempt, no retries.

    Args:
        client: A client from :func:`make_client`.
        state: What the questions are about. Only what the judgment needs.
        questions: Named questions from :func:`noul` / :func:`choice`.
        timeout_s: Overrides the client's timeout for this request.

    Returns:
        The decoded answers, the model that answered, and input tokens.

    Raises:
        GlideUnavailable: Timeout, transport failure, a non-200 status, or a
            body that is not a System One response.
    """
    body = {"model": _CONFIG.model, "state": state, "questions": questions}
    try:
        if timeout_s is None:
            response = await client.post(_PATH, json=body)
        else:
            response = await client.post(_PATH, json=body, timeout=timeout_s)
    except httpx.TimeoutException:
        raise GlideUnavailable("timeout") from None
    except httpx.HTTPError as exc:
        # Class name only: exception text can carry the request.
        raise GlideUnavailable(type(exc).__name__) from None
    if response.status_code != httpx.codes.OK:
        raise GlideUnavailable(f"http_{response.status_code}")
    try:
        payload = response.json()
        return GlideResponse(
            answers=payload["answers"],
            model=payload["model"],
            input_tokens=payload["usage"]["input_tokens"],
        )
    except (KeyError, TypeError, ValueError):
        # ValueError covers undecodable JSON and pydantic validation.
        raise GlideUnavailable("malformed_response") from None


__all__ = [
    "API_KEY_ENV",
    "GlideResponse",
    "GlideUnavailable",
    "Question",
    "Questions",
    "api_key",
    "ask",
    "choice",
    "make_client",
    "noul",
]
