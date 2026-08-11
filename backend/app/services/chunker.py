"""Page-aware character chunker (docs/ingestion.md §4.3, research.md R3).

Pure and deterministic: no tokenizer dependency. A fixed prose ratio
CHARS_PER_TOKEN ≈ 2.4 turns the token targets from docs/ingestion.md §4.3
(~500 chunk / ~50 overlap tokens) into character windows. Windows never cross
pages unless a single page cannot hold a full chunk — page alignment is what
Phase 6 retrieval cites (page_number, docs/rag.md §5).
"""

from __future__ import annotations

from dataclasses import dataclass

CHARS_PER_TOKEN = 2.4


class ParseError(Exception):
    """Text extraction produced no usable content (permanent failure).

    Raised by chunk_pages for empty input (scanned/blank PDFs) so the pipeline
    maps it to status='failed' (docs/ingestion.md §4.2, research.md R4).
    """


@dataclass(frozen=True)
class Chunk:
    """One page-aware chunk of extracted text."""

    content: str
    page_start: int  # 1-based page of the first page contributing text
    page_end: int  # 1-based page of the last page contributing text

    @property
    def token_count(self) -> int:
        return round(len(self.content) / CHARS_PER_TOKEN)


def _boundary_cut(text: str, start: int, preferred_end: int) -> int:
    """Cut at the last whitespace at or before preferred_end (word boundary).

    The backward walk never goes below `start`. Hard fallback: cut exactly at
    preferred_end when the whole window is one unbroken run of characters.
    """
    if preferred_end >= len(text):
        return len(text)
    end = preferred_end
    while end > start and not text[end - 1].isspace():
        end -= 1
    if end <= start:
        return preferred_end
    return end


def _page_windows(page: str, size_chars: int, overlap_chars: int) -> list[str]:
    """Split one page's text into overlapping windows of at most size_chars."""
    if len(page) <= size_chars:
        return [page]
    windows: list[str] = []
    start = 0
    while start < len(page):
        preferred_end = min(start + size_chars, len(page))
        end = _boundary_cut(page, start, preferred_end)
        windows.append(page[start:end])
        if end >= len(page):
            break
        if end - start <= overlap_chars:
            start = end  # nothing worth overlapping in a short window
        else:
            start = max(end - overlap_chars, start + 1)
    return windows


def chunk_pages(
    pages: list[str],
    *,
    chunk_size_chars: int,
    overlap_chars: int,
) -> list[Chunk]:
    """Split page texts into page-aware chunks (research.md R3).

    - Only pages with non-empty stripped text contribute.
    - Each page is windowed independently (word-boundary splits, overlap).
    - A trailing window is merged with the next page's first window only when
      the merge stays under the size cap — chunks stay page-aligned otherwise.
    - Raises ParseError when no usable text exists at all.
    """
    if chunk_size_chars <= 0 or overlap_chars < 0:
        raise ValueError("chunk_size_chars must be > 0 and overlap_chars >= 0")
    if overlap_chars >= chunk_size_chars:
        raise ValueError("overlap_chars must be smaller than chunk_size_chars")

    non_empty = [(index, page) for index, page in enumerate(pages) if page.strip()]
    if not non_empty:
        raise ParseError("no text extracted — scanned or empty PDF")

    chunks: list[Chunk] = []
    open_chunk: Chunk | None = None
    for page_index, page_text in non_empty:
        for window in _page_windows(page_text, chunk_size_chars, overlap_chars):
            if open_chunk is not None and open_chunk.page_end <= page_index:
                merged_len = len(open_chunk.content) + 1 + len(window)
                if merged_len <= chunk_size_chars:
                    open_chunk = Chunk(
                        content=f"{open_chunk.content}\n{window}",
                        page_start=open_chunk.page_start,
                        page_end=page_index + 1,
                    )
                    continue
            if open_chunk is not None:
                chunks.append(open_chunk)
            open_chunk = Chunk(
                content=window,
                page_start=page_index + 1,
                page_end=page_index + 1,
            )
    if open_chunk is not None:
        chunks.append(open_chunk)
    return chunks
