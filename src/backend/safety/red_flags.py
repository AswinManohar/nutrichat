"""Red-flag screen: dangerous patient messages get a fixed reply, no model.

Rules live in config/clinical/red_flags.yaml (written by the dietitians). The
whole message is searched; the first rule in file order that matches wins. The
file is re-read when its mtime changes, and compiled patterns are cached per
file hash. If the file cannot be loaded the screen raises, and the caller must
fail closed (spec 013, FR-015 to FR-018).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import yaml

from backend.safety.tables import (
    RedFlags,
    TablesUnavailable,
    clinical_dir,
    load_red_flags,
)

logger = logging.getLogger(__name__)

# Used only when red_flags.yaml itself cannot be read, so its own
# fallback_unavailable_text is out of reach.
HARD_FALLBACK_TEXT = (
    "I can't reply right now. If this is urgent, contact your care team "
    "or emergency services."
)


class RedFlagsUnavailable(Exception):
    """The red-flag list cannot be loaded; the caller must fail closed."""


@dataclass(frozen=True)
class RedFlagMatch:
    """The rule a message matched."""

    rule_id: str
    label: str
    response: str
    rules_version: str


@dataclass(frozen=True)
class _Compiled:
    rule_id: str
    label: str
    response: str
    patterns: tuple[re.Pattern[str], ...]


# (file hash, compiled rules): rebuilt only when the file's content changes.
_compiled: tuple[str, tuple[_Compiled, ...]] | None = None


def _rules() -> tuple[str, tuple[_Compiled, ...]]:
    global _compiled
    try:
        digest, parsed = load_red_flags()
    except TablesUnavailable as exc:
        raise RedFlagsUnavailable(str(exc)) from exc
    if _compiled is None or _compiled[0] != digest:
        _compiled = (digest, _compile(parsed))
    return _compiled


def _compile(parsed: RedFlags) -> tuple[_Compiled, ...]:
    return tuple(
        _Compiled(
            rule.id,
            rule.label,
            rule.response,
            tuple(re.compile(p, re.IGNORECASE) for p in rule.patterns),
        )
        for rule in parsed.rules
    )


def screen(message: str) -> RedFlagMatch | None:
    """Search the whole message for a red-flag pattern.

    Args:
        message: The patient's text.

    Returns:
        The first matching rule in file order, or None.

    Raises:
        RedFlagsUnavailable: If the rule file cannot be loaded.
    """
    digest, rules = _rules()
    for rule in rules:
        if any(p.search(message) for p in rule.patterns):
            return RedFlagMatch(rule.rule_id, rule.label, rule.response, digest)
    return None


def fallback_text() -> str:
    """Fixed reply for when the list is unreadable.

    Returns:
        The file's fallback_unavailable_text if that key can still be read,
        else HARD_FALLBACK_TEXT.
    """
    try:
        raw = yaml.safe_load((clinical_dir() / "red_flags.yaml").read_bytes())
        text = raw["fallback_unavailable_text"]
        if isinstance(text, str) and text.strip():
            return text
    except (OSError, yaml.YAMLError, TypeError, KeyError) as exc:
        logger.error("red_flags.yaml fallback text unreadable: %s", exc)
    return HARD_FALLBACK_TEXT
