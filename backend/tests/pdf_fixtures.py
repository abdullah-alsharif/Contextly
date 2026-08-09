"""Hand-built minimal PDF fixtures (research.md R7; docs/testing.md §4).

make_pdf builds a valid single-page-per-entry PDF with a correct xref table from
plain text lines, so worker tests need no binary fixtures and can craft exact
page content. Also ships corrupt and no-text helpers.
"""
from __future__ import annotations


def _escape_pdf_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_pdf(objects: list[bytes], *, root: int = 1) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    count = len(objects) + 1
    out += f"xref\n0 {count}\n".encode()
    out += b"0000000000 65535 f \r\n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \r\n".encode()
    out += (
        f"trailer\n<< /Size {count} /Root {root} 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF"
    ).encode()
    return bytes(out)


def make_pdf(pages: list[str]) -> bytes:
    """Build a valid PDF with one page per entry, each drawing the given text."""
    if not pages:
        raise ValueError("make_pdf needs at least one page")
    catalog_index = 1
    font_index = 2
    pages_index = 3
    objects: list[bytes] = []
    kids: list[str] = []
    next_index = 4
    for text in pages:
        page_index = next_index
        content_index = next_index + 1
        next_index += 2
        stream = f"BT /F1 12 Tf 72 720 Td ({_escape_pdf_string(text)}) Tj ET".encode()
        content_body = (
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
        page_body = (
            f"<< /Type /Page /Parent {pages_index} 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_index} 0 R "
            f"/Resources << /Font << /F1 {font_index} 0 R >> >> >>"
        ).encode()
        objects.append(page_body)
        objects.append(content_body)
        kids.append(f"{page_index} 0 R")
    font_body = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    catalog_body = f"<< /Type /Catalog /Pages {pages_index} 0 R >>".encode()
    pages_body = (
        f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode()
    )
    all_objects = [catalog_body, font_body, pages_body] + objects
    return _build_pdf(all_objects, root=catalog_index)


def make_corrupt_pdf() -> bytes:
    """Bytes that look like a PDF but fail parsing (PdfReadError)."""
    return b"%PDF-1.4\n" + b"\x00garbage\x00" * 64 + b"%%EOF"


def make_no_text_pdf() -> bytes:
    """Valid PDF whose pages contain no extractable text (scanned-style)."""
    return make_pdf(["", ""])


def make_poison_pdf() -> bytes:
    """Well-formed PDF that parses but crashes pypdf's extract_text.

    The page draws with a Type0 font that lacks /DescendantFonts; PdfReader
    accepts the document (pages list works) but extract_text raises
    KeyError('/DescendantFonts'). Proves the worker survives arbitrary input.
    """
    stream = b"BT /F1 12 Tf 72 720 Td (hi) Tj ET"
    content_body = (
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
    )
    page_body = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>"
    )
    font_body = (
        b"<< /Type /Font /Subtype /Type0 /BaseFont /Foo /Encoding /Identity-H >>"
    )
    objects = [
        b"<< /Type /Catalog /Pages 3 0 R >>",
        b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        page_body,
        content_body,
        font_body,
    ]
    return _build_pdf(objects)
