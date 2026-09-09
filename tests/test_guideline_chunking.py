from __future__ import annotations

from pathlib import Path

import pytest

from backend.guidelines.chunking import (
    MAX_CHUNK_WORDS,
    Chunk,
    FrontmatterError,
    _split_long,
    content_hash,
    parse_markdown,
)

_FRONTMATTER = """---
source_id: demo
title: Demo Guideline
url: https://example.org/demo
condition: general
license: public domain
---
"""


def _write(tmp_path: Path, body: str, name: str = "demo.md") -> Path:
    path = tmp_path / name
    path.write_text(_FRONTMATTER + body, encoding="utf-8")
    return path


def test_each_heading_starts_a_chunk_with_section_path(tmp_path: Path) -> None:
    body = (
        "## Chapter 1\n\nIntro paragraph.\n\n"
        "### Core elements\n\nVegetables and fruit.\n\n"
        "## Chapter 2\n\nLimits.\n"
    )
    chunks = parse_markdown(_write(tmp_path, body))

    assert [c.section for c in chunks] == [
        "Chapter 1",
        "Chapter 1 > Core elements",
        "Chapter 2",
    ]
    assert [c.ordinal for c in chunks] == [0, 1, 2]
    assert chunks[1].text == "Vegetables and fruit."
    assert all(isinstance(c, Chunk) for c in chunks)
    assert chunks[0].source_title == "Demo Guideline"
    assert chunks[0].condition == "general"


def test_hash_is_stable_and_depends_on_section_and_text() -> None:
    a = content_hash("demo", "Chapter 1", "text")
    assert a == content_hash("demo", "Chapter 1", "text")
    assert a != content_hash("demo", "Chapter 2", "text")
    assert a != content_hash("demo", "Chapter 1", "other")
    assert len(a) == 64


def test_long_section_splits_at_paragraphs_with_one_paragraph_overlap() -> None:
    paras = [f"p{i} " + ("word " * 99).strip() for i in range(1, 6)]  # 100 words each
    pieces = _split_long("\n\n".join(paras), max_words=250)

    assert len(pieces) == 4
    assert pieces[0].startswith("p1 ") and pieces[0].endswith(paras[1])
    assert pieces[1].startswith("p2 ")  # overlap: last paragraph of piece 0
    assert pieces[3].startswith("p4 ") and pieces[3].endswith(paras[4])


def test_short_section_is_not_split() -> None:
    text = "one paragraph\n\ntwo paragraph"
    assert _split_long(text, max_words=MAX_CHUNK_WORDS) == [text]


def test_missing_frontmatter_key_raises_naming_the_file(tmp_path: Path) -> None:
    path = tmp_path / "demo.md"
    path.write_text(
        "---\nsource_id: demo\ntitle: T\nurl: u\ncondition: general\n---\n## A\n\nx\n",
        encoding="utf-8",
    )
    with pytest.raises(FrontmatterError, match="demo.md"):
        parse_markdown(path)


def test_source_id_must_match_filename(tmp_path: Path) -> None:
    path = _write(tmp_path, "## A\n\nx\n", name="other.md")
    with pytest.raises(FrontmatterError, match="source_id"):
        parse_markdown(path)


def test_a_dashed_line_that_is_not_exactly_three_dashes_is_not_the_fence(
    tmp_path: Path,
) -> None:
    """``----`` opens no body: the header is unterminated, not split early."""
    path = tmp_path / "demo.md"
    path.write_text(
        "---\n"
        "source_id: demo\n"
        "title: Demo Guideline\n"
        "url: https://example.org/demo\n"
        "condition: general\n"
        "license: public domain\n"
        "----\n"
        "## Chapter 1\n\nBody text.\n",
        encoding="utf-8",
    )

    with pytest.raises(FrontmatterError, match="unterminated"):
        parse_markdown(path)


def test_a_fence_with_trailing_text_is_not_the_fence(tmp_path: Path) -> None:
    path = tmp_path / "demo.md"
    path.write_text(
        "---\n"
        "source_id: demo\n"
        "title: Demo Guideline\n"
        "url: https://example.org/demo\n"
        "condition: general\n"
        "license: public domain\n"
        "--- x\n"
        "## Chapter 1\n\nBody text.\n",
        encoding="utf-8",
    )

    with pytest.raises(FrontmatterError, match="unterminated"):
        parse_markdown(path)


def test_horizontal_rule_inside_a_line_does_not_close_the_frontmatter(
    tmp_path: Path,
) -> None:
    """A dashed run that is not its own line must not end the header."""
    path = tmp_path / "demo.md"
    path.write_text(
        "---\n"
        "source_id: demo\n"
        "title: Demo Guideline\n"
        "url: https://example.org/demo\n"
        "condition: general\n"
        "license: public domain\n"
        "---\n"
        "## Chapter 1\n\nA sentence with a stray ---dash run--- inside it.\n",
        encoding="utf-8",
    )

    chunks = parse_markdown(path)

    assert [c.section for c in chunks] == ["Chapter 1"]
    assert chunks[0].source_title == "Demo Guideline"
    assert "stray ---dash run--- inside it." in chunks[0].text
