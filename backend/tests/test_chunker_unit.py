"""Chunker unit tests (docs/testing.md §1: token counts, overlap correctness,
page attribution, empty-text handling; research.md R3). No database required.

Defaults mirror docs/ingestion.md §4.3: 500 tokens ≈ 1200 chars, 50 tokens
≈ 120 chars at CHARS_PER_TOKEN ≈ 2.4.
"""

from __future__ import annotations

import pytest

from app.services.chunker import CHARS_PER_TOKEN, Chunk, ParseError, chunk_pages

SIZE = round(500 * CHARS_PER_TOKEN)  # 1200
OVERLAP = round(50 * CHARS_PER_TOKEN)  # 120


def test_empty_page_list_raises_parse_error() -> None:
    with pytest.raises(ParseError):
        chunk_pages([], chunk_size_chars=SIZE, overlap_chars=OVERLAP)


def test_all_blank_pages_raise_parse_error() -> None:
    with pytest.raises(ParseError):
        chunk_pages(["   ", "\n\t", ""], chunk_size_chars=SIZE, overlap_chars=OVERLAP)


def test_single_page_single_chunk() -> None:
    text = "Just a short page."
    chunks = chunk_pages([text], chunk_size_chars=SIZE, overlap_chars=OVERLAP)
    assert len(chunks) == 1
    assert chunks[0].content == text
    assert chunks[0].page_start == 1
    assert chunks[0].page_end == 1


def test_pages_merge_across_when_they_fit() -> None:
    chunks = chunk_pages(
        ["Page one text", "Page two text"], chunk_size_chars=SIZE, overlap_chars=OVERLAP
    )
    assert len(chunks) == 1
    assert chunks[0].page_start == 1
    assert chunks[0].page_end == 2
    assert "Page one text" in chunks[0].content
    assert "Page two text" in chunks[0].content


def test_blank_pages_are_skipped() -> None:
    chunks = chunk_pages(
        ["", "Real content", "   ", "More content"],
        chunk_size_chars=SIZE,
        overlap_chars=OVERLAP,
    )
    assert len(chunks) == 1
    assert chunks[0].page_start == 2  # blank pages contribute nothing
    assert chunks[0].page_end == 4
    assert chunks[0].content == "Real content\nMore content"


def test_windows_respect_size_cap() -> None:
    page = "word " * (SIZE * 3)
    chunks = chunk_pages([page], chunk_size_chars=SIZE, overlap_chars=OVERLAP)
    assert len(chunks) >= 3
    assert all(len(c.content) <= SIZE for c in chunks)


def test_windows_overlap() -> None:
    page = "word " * (SIZE * 2)
    chunks = chunk_pages([page], chunk_size_chars=SIZE, overlap_chars=OVERLAP)
    assert len(chunks) >= 2
    a, b = chunks[0].content, chunks[1].content
    assert a[-OVERLAP:] in b


def test_word_boundary_split_not_mid_word() -> None:
    page = "alpha " + "x" * (SIZE + 100) + " omega"
    chunks = chunk_pages([page], chunk_size_chars=SIZE, overlap_chars=OVERLAP)
    assert all(c.content for c in chunks)  # no empty windows
    assert any(c.content == "x" * SIZE for c in chunks)  # hard fallback inside run


def test_cross_page_merge_only_when_under_cap() -> None:
    tail = "trailing words"
    page_two = "fits " * 50 + tail
    chunks = chunk_pages(
        ["A" * 50 + " " + tail] + [page_two],
        chunk_size_chars=SIZE,
        overlap_chars=OVERLAP,
    )
    assert len(chunks) == 1
    assert chunks[0].page_start == 1
    assert chunks[0].page_end == 2
    assert chunks[0].content.endswith(tail)


def test_no_cross_page_merge_when_exceeding_cap() -> None:
    big_tail = "Z" * (SIZE // 2)
    chunks = chunk_pages(
        ["A" * 100, "B" * (SIZE) + " " + big_tail],
        chunk_size_chars=SIZE,
        overlap_chars=OVERLAP,
    )
    assert all(c.page_start == c.page_end for c in chunks)


def test_token_count_uses_prose_ratio() -> None:
    chunks = chunk_pages(["hello " * 50], chunk_size_chars=SIZE, overlap_chars=OVERLAP)
    assert len(chunks) == 1
    assert chunks[0].token_count == round(len(chunks[0].content) / CHARS_PER_TOKEN)


def test_chunk_dataclass_frozen() -> None:
    chunk = Chunk(content="x", page_start=1, page_end=1)
    with pytest.raises(Exception):
        chunk.content = "y"  # type: ignore[misc]


def test_invalid_sizes_rejected() -> None:
    with pytest.raises(ValueError):
        chunk_pages(["x"], chunk_size_chars=0, overlap_chars=0)
    with pytest.raises(ValueError):
        chunk_pages(["x"], chunk_size_chars=10, overlap_chars=10)
    with pytest.raises(ValueError):
        chunk_pages(["x"], chunk_size_chars=10, overlap_chars=-1)
