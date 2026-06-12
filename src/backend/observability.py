"""Logfire/OpenTelemetry setup. Call configure_observability() once per process."""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING

import logfire

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Matches a long base64 blob (e.g. an inlined image) on its own.
_BASE64_BLOB_RE = re.compile(r"^[A-Za-z0-9+/=\s]{1024,}$")
_DATA_URI_RE = re.compile(r"^data:image/[a-zA-Z0-9+.-]+;base64,")

_configured = False


def _scrub_extra(match: logfire.ScrubMatch) -> str | None:
    """Redact image payloads from span attributes before export.

    Args:
        match: Scrub match describing the attribute path, value, and the
            regex match that triggered scrubbing.

    Returns:
        Replacement value when the match looks like an image payload,
        otherwise ``None`` to keep the default scrubbing behavior.
    """
    path_str = "".join(str(part) for part in match.path)
    if "image_b64" in path_str:
        return "<redacted image>"

    value = match.value
    if isinstance(value, str) and (
        _DATA_URI_RE.match(value) or _BASE64_BLOB_RE.match(value)
    ):
        return "<redacted image>"

    return None


def configure_observability(app: FastAPI | None = None) -> None:
    """Configure Logfire tracing and instrumentation for this process.

    Safe to call multiple times — only the first call has an effect. Without
    a `LOGFIRE_TOKEN`, configuration is a local no-op (`send_to_logfire`
    is `"if-token-present"`), so this is safe for tests and CI.

    Args:
        app: FastAPI app instance to instrument, if running in the API
            process. Pass `None` from worker processes.
    """
    global _configured
    if _configured:
        return
    _configured = True

    logfire.configure(
        service_name="nutrichat",
        environment=os.environ.get("LOGFIRE_ENVIRONMENT", "dev"),
        send_to_logfire="if-token-present",
        scrubbing=logfire.ScrubbingOptions(callback=_scrub_extra),
    )

    if app is not None:
        try:
            logfire.instrument_fastapi(app)
        except ImportError:
            logger.warning("logfire FastAPI instrumentation unavailable")

    try:
        logfire.instrument_asyncpg()
    except ImportError:
        logger.warning("logfire asyncpg instrumentation unavailable")

    try:
        logfire.instrument_redis()
    except ImportError:
        logger.warning("logfire redis instrumentation unavailable")

    try:
        logfire.instrument_celery()
    except ImportError:
        logger.warning("logfire celery instrumentation unavailable")

    try:
        logfire.instrument_aiohttp_client()
    except ImportError:
        logger.warning("logfire aiohttp_client instrumentation unavailable")

    try:
        from opentelemetry.instrumentation.langchain import LangchainInstrumentor

        LangchainInstrumentor().instrument()
    except ImportError:
        logger.warning("opentelemetry langchain instrumentation unavailable")

    try:
        logfire.instrument_pydantic_ai()
    except ImportError:
        logger.warning("logfire pydantic-ai instrumentation unavailable")


__all__ = ["configure_observability"]
