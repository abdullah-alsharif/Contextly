"""Upload guard rails (docs/security.md §3, docs/api.md §2, spec SC-003).

Asserted at the API boundary with the local provider: a body that is not a PDF
is rejected by magic bytes even when content-type and extension both claim PDF;
an oversized upload is rejected pre-processing with 413 and leaves no row or
object; a hostile filename is sanitized for display while the storage key stays
server-generated `{user_id}/docs/{document_id}.pdf`.

DB-gated (tests/security/_harness.py).
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.services.documents import sanitize_filename
from tests.pdf_fixtures import make_pdf
from tests.security import _harness

pytestmark = _harness.DB_GATE

USER = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")


def _token() -> str:
    return _harness.token(USER)


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    return _harness.make_client(str(tmp_path_factory.mktemp("storage")))


@pytest.fixture(scope="module")
def cleanup() -> None:
    yield
    with psycopg.connect(_harness.database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("delete from documents where user_id = %s", (USER,))
            cur.execute("delete from profiles where id = %s", (USER,))
        conn.commit()


def _upload(
    client: TestClient,
    content: bytes,
    *,
    filename: str = "x.pdf",
    content_type: str = "application/pdf",
) -> tuple[int, dict]:
    response = client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {_token()}"},
        files={"file": (filename, content, content_type)},
    )
    if not response.content:
        return response.status_code, {}
    return response.status_code, response.json()


def test_non_pdf_declaring_pdf_content_type_rejected_400(client, cleanup) -> None:
    # content-type AND extension claim PDF, but the bytes are an HTML file:
    # the magic-byte check must catch it (docs/security.md §3).
    html = b"<html><body>please parse me</body></html>"
    status, body = _upload(client, html)
    assert status == 400
    assert body.get("detail")


def test_oversized_upload_413_no_row_no_object(client, cleanup) -> None:
    big = b"%PDF-" + b"\0" * (_harness.MAX_UPLOAD + 1)
    status, body = _upload(client, big)
    assert status == 413
    assert body.get("detail")

    with psycopg.connect(_harness.database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from documents where user_id = %s", (USER,))
            assert cur.fetchone()[0] == 0

    storage_dir = client.app.state.storage_provider.root  # type: ignore[attr-defined]
    user_dir = storage_dir / str(USER)
    assert not user_dir.exists() or not any(user_dir.iterdir())


def test_hostile_filename_sanitized_and_key_server_generated(client, cleanup) -> None:
    # A raw multipart body carries a real tab byte in the filename header
    # (httpx would percent-encode it, which is not how a hostile client sends
    # it). The server must strip path components + the control char for the
    # display name, and derive the storage key server-side, never from the
    # client filename (docs/security.md §3).
    payload = make_pdf(["ok"])
    boundary = b"X-CONTEXTLY-BOUNDARY"
    raw = (
        b"--" + boundary + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="../../evil/refund\tpolicy.pdf"\r\n'
        b"Content-Type: application/pdf\r\n\r\n"
        + payload
        + b"\r\n--" + boundary + b"--\r\n"
    )
    response = client.post(
        "/api/v1/documents",
        headers={
            "Authorization": f"Bearer {_token()}",
            "Content-Type": f"multipart/form-data; boundary={boundary.decode()}",
        },
        content=raw,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["filename"] == "refundpolicy.pdf"

    with psycopg.connect(_harness.database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select storage_path from documents where id = %s", (body["id"],)
            )
            storage_path = cur.fetchone()[0]
    assert storage_path == f"{USER}/docs/{body['id']}.pdf"
    assert "evil" not in storage_path and ".." not in storage_path


def test_valid_pdf_upload_201_sanity(client, cleanup) -> None:
    payload = make_pdf(["hello"])
    status, body = _upload(client, payload, filename="notes.pdf")
    assert status == 201
    assert body["filename"] == "notes.pdf"
    assert body["file_size_bytes"] == len(payload)


def test_sanitize_filename_strips_control_chars_and_path() -> None:
    assert sanitize_filename("\x01\x02payroll\x7f.pdf") == "payroll.pdf"
    assert sanitize_filename("a/b/c/notes.pdf") == "notes.pdf"