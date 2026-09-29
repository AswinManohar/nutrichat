"""Parse a guideline markdown file into embeddable chunks. Pure, no I/O."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

# Roughly 400 tokens of English prose. No tokenizer dependency: the
# ingest path only needs a stable, approximate cap.
MAX_CHUNK_WORDS = 300

_HEADING_RE = re.compile(r"^(#{2,3})\s+(.*\S)\s*$")
_CLOSING_DELIMITER_RE = re.compile(r"^---[ \t]*$", re.MULTILINE)


class FrontmatterError(ValueError):
    """Raised when a guideline file has missing or inconsistent frontmatter."""


class Frontmatter(BaseModel):
    """Required YAML header of every ``docs/guidelines/<source_id>.md`` file."""

    source_id: str
    title: str
    url: str
    condition: str
    license: str

    model_config = ConfigDict(extra="forbid")


class Chunk(BaseModel):
    """One passage ready for embedding and insertion into guideline_chunk."""

    source_id: str
    source_title: str
    source_url: str
    condition: str
    section: str
    ordinal: int
    text: str
    content_hash: str

    model_config = ConfigDict(extra="forbid")


def content_hash(source_id: str, section: str, text: str) -> str:
    """Return the sha256 hex digest identifying a chunk across ingest runs."""
    payload = "\n".join((source_id, section, text)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _word_count(text: str) -> int:
    """Count whitespace-separated words."""
    return len(text.split())


def _split_frontmatter(raw: str, path: Path) -> tuple[Frontmatter, str]:
    """Split ``---`` delimited YAML frontmatter from the markdown body.

    Args:
        raw: Full file contents.
        path: File path, used only for error messages.

    Returns:
        Validated frontmatter and the remaining body text.

    Raises:
        FrontmatterError: If the header is missing, malformed, or lacks a key.
    """
    if not raw.startswith("---\n"):
        raise FrontmatterError(f"{path.name}: missing YAML frontmatter")
    # The closing delimiter is a line that is exactly "---", so a horizontal
    # rule written inside a paragraph does not end the header early.
    match = _CLOSING_DELIMITER_RE.search(raw, 4)
    if match is None:
        raise FrontmatterError(f"{path.name}: unterminated YAML frontmatter")
    header = raw[4 : match.start()]
    body = raw[match.end() :].lstrip("\n")
    try:
        fields = yaml.safe_load(header) or {}
        frontmatter = Frontmatter(**fields)
    except (yaml.YAMLError, ValidationError, TypeError) as exc:
        raise FrontmatterError(f"{path.name}: invalid frontmatter: {exc}") from exc
    if frontmatter.source_id != path.stem:
        raise FrontmatterError(
            f"{path.name}: source_id '{frontmatter.source_id}' must equal "
            f"the filename stem '{path.stem}'"
        )
    return frontmatter, body


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Split the body at every ``##`` / ``###`` heading.

    Returns:
        List of (section path joined with " > ", section text) pairs in
        document order. Text before the first heading is emitted under
        "Introduction" when non-empty.
    """
    sections: list[tuple[str, str]] = []
    h2: str | None = None
    h3: str | None = None
    buffer: list[str] = []
    current = "Introduction"

    def flush() -> None:
        text = "\n".join(buffer).strip()
        if text:
            sections.append((current, text))
        buffer.clear()

    for line in body.splitlines():
        match = _HEADING_RE.match(line)
        if match is None:
            buffer.append(line)
            continue
        flush()
        level, title = len(match.group(1)), match.group(2)
        if level == 2:
            h2, h3 = title, None
        else:
            h3 = title
        current = " > ".join(part for part in (h2, h3) if part)
    flush()
    return sections


def _split_long(text: str, max_words: int = MAX_CHUNK_WORDS) -> list[str]:
    """Split text longer than ``max_words`` at paragraph boundaries.

    Consecutive pieces share one paragraph so a recommendation that spans
    a boundary is still retrievable whole.

    Args:
        text: Section text with blank-line separated paragraphs.
        max_words: Soft cap per piece; a single oversized paragraph is
            kept intact.

    Returns:
        One or more pieces, each a "\\n\\n"-joined run of paragraphs.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    joined = "\n\n".join(paragraphs)
    if _word_count(joined) <= max_words:
        return [joined]

    pieces: list[str] = []
    current: list[str] = []
    for para in paragraphs:
        if current and _word_count("\n\n".join(current + [para])) > max_words:
            pieces.append("\n\n".join(current))
            current = [current[-1], para]
        else:
            current.append(para)
    if current:
        pieces.append("\n\n".join(current))
    return pieces


def parse_markdown(path: Path) -> list[Chunk]:
    """Parse one guideline file into ordered, hashed chunks.

    Args:
        path: ``docs/guidelines/<source_id>.md``.

    Returns:
        Chunks in document order with ``ordinal`` 0..n-1.

    Raises:
        FrontmatterError: See _split_frontmatter.
    """
    frontmatter, body = _split_frontmatter(path.read_text(encoding="utf-8"), path)
    chunks: list[Chunk] = []
    for section, section_text in _split_sections(body):
        for piece in _split_long(section_text):
            chunks.append(
                Chunk(
                    source_id=frontmatter.source_id,
                    source_title=frontmatter.title,
                    source_url=frontmatter.url,
                    condition=frontmatter.condition,
                    section=section,
                    ordinal=len(chunks),
                    text=piece,
                    content_hash=content_hash(frontmatter.source_id, section, piece),
                )
            )
    return chunks


__all__ = [
    "MAX_CHUNK_WORDS",
    "Chunk",
    "Frontmatter",
    "FrontmatterError",
    "content_hash",
    "parse_markdown",
]
