"""parse_pdf sanitization unit tests (docs/ingestion.md §2: broken PDF text
encodings emit C0 controls — NUL and friends — that Postgres text columns
cannot store). No database required."""

from __future__ import annotations

import io

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.services.pipeline import parse_pdf
from app.services.text_clean import replace_control_chars


def test_replace_control_chars_drops_nul_and_other_c0_controls() -> None:
    text = "a\x00b\x01c\x08d\x0b\x0c\x1fe\tg\nh\ri"
    assert replace_control_chars(text) == "a b c d   e\tg\nh\ri"


def test_replace_control_chars_keeps_normal_whitespace() -> None:
    assert replace_control_chars("plain \t\n\r text") == "plain \t\n\r text"


def test_parse_pdf_extracts_normal_text_unchanged() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    writer.pages[0][NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    page = writer.pages[0]
    page[NameObject("/Contents")] = _stream(b"BT /F1 12 Tf 72 720 Td (hello) Tj ET")
    buf = io.BytesIO()
    writer.write(buf)

    assert parse_pdf(buf.getvalue()) == ["hello"]


def _stream(data: bytes) -> DecodedStreamObject:
    stream = DecodedStreamObject()
    stream.set_data(data)
    return stream
