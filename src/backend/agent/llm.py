from __future__ import annotations

import os

from google import genai
from google.genai import types as genai_types
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from pydantic_ai.providers.google import GoogleProvider

from backend.config import get_tunables

_TUNABLES = get_tunables()

FLASH_LITE_MODEL = _TUNABLES.models.extraction
COACHING_MODEL = _TUNABLES.models.coaching
EMBEDDING_MODEL = _TUNABLES.models.embedding
EMBEDDING_DIM = _TUNABLES.models.embedding_dim


def make_llm(
    model: str = FLASH_LITE_MODEL,
    *,
    thinking_budget: int | None = None,
    retries: int | None = None,
    **kwargs: object,
) -> ChatGoogleGenerativeAI:
    """Construct a Gemini chat model with the project's API key.

    Args:
        model: Gemini model name.
        thinking_budget: Reasoning-token budget. Defaults to
            token_limits.extraction_thinking_budget (0 = thinking off) so every
            extraction-tier caller skips the ~1-3s dynamic-thinking phase on
            these structured-output tasks. Pass an explicit value to override.
        retries: Retries after a failed call; None keeps the client default.
        **kwargs: Extra constructor args, e.g. max_output_tokens.

    Returns:
        Configured ChatGoogleGenerativeAI instance.
    """
    if thinking_budget is None:
        thinking_budget = _TUNABLES.token_limits.extraction_thinking_budget
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=os.environ.get("GOOGLE_API_KEY", ""),
        thinking_budget=thinking_budget,
        # The client counts attempts, the first call included.
        **({"max_retries": retries + 1} if retries is not None else {}),
        **kwargs,
    )


def gemini_provider(retries: int) -> GoogleProvider:
    """A Pydantic AI Gemini provider that retries failed calls.

    The default provider does not retry, so one 429 or 5xx fails the turn.

    Args:
        retries: Retries after a failed call (attempts = retries + 1).

    Returns:
        A provider for ``GoogleModel(..., provider=...)``.
    """
    client = genai.Client(
        api_key=os.environ.get("GOOGLE_API_KEY", ""),
        http_options=genai_types.HttpOptions(
            retry_options=genai_types.HttpRetryOptions(attempts=retries + 1)
        ),
    )
    return GoogleProvider(client=client)


async def embed_text(text: str) -> list[float]:
    """Embed a string with the project's embedding model.

    Args:
        text: Text to embed.

    Returns:
        Embedding vector of EMBEDDING_DIM dimensions.
    """
    embeddings = GoogleGenerativeAIEmbeddings(
        model=EMBEDDING_MODEL,
        google_api_key=os.environ.get("GOOGLE_API_KEY", ""),
        output_dimensionality=EMBEDDING_DIM,
    )
    return await embeddings.aembed_query(text)


__all__ = [
    "FLASH_LITE_MODEL",
    "COACHING_MODEL",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIM",
    "make_llm",
    "embed_text",
]
