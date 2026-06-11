from __future__ import annotations

import os

from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from backend.config import get_tunables

_TUNABLES = get_tunables()

FLASH_LITE_MODEL = _TUNABLES.models.extraction
COACHING_MODEL = _TUNABLES.models.coaching
EMBEDDING_MODEL = _TUNABLES.models.embedding
EMBEDDING_DIM = _TUNABLES.models.embedding_dim


def make_llm(model: str = FLASH_LITE_MODEL, **kwargs: object) -> ChatGoogleGenerativeAI:
    """Construct a Gemini chat model with the project's API key.

    Args:
        model: Gemini model name.
        **kwargs: Extra constructor args, e.g. max_output_tokens.

    Returns:
        Configured ChatGoogleGenerativeAI instance.
    """
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=os.environ.get("GOOGLE_API_KEY", ""),
        **kwargs,
    )


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
