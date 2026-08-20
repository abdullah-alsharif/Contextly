"""Logs API tests (specs/016 US2/US3; contracts/logs.md §2).

DB-gated (same pattern as test_documents_api.py). Covers GET /api/v1/logs:
401 without token, newest-first ordering with an id-desc tiebreak, offset/limit
paging (default 50, bounds 1–100 → 422), payload shape (never user_id /
storage_path), foreign rows invisible by construction, and the US3 filter
matrix (action_type, inclusive from/to with date-only UTC-day bounds, combined,
422s).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.security.dev import dev_token
from app.db.session import get_db
from app.main import create_app

DEV_SECRET = "contextly-dev-secret-0123456789abcdef"

USER_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

_TEST_ENGINE = create_async_engine(
    os.getenv("DATABASE_URL", "postgresql://localhost/contextly").replace(
        "postgresql://", "postgresql+asyncpg://", 1
    ),
    poolclass=NullPool,
)
_TestSessionFactory = async_sessionmaker(_TEST_ENGINE, expire_on_commit=False)


def _database_reachable() -> bool:
    url = os.getenv("DATABASE_URL")
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=1) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _database_reachable(), reason="DATABASE_URL not reachable"
)


def _token(user: uuid.UUID) -> str:
    return dev_token(user, secret=DEV_SECRET)


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    storage_dir = tmp_path_factory.mktemp("storage")
    settings = Settings(
        database_url=os.environ["DATABASE_URL"],
        auth_mode="dev",
        app_env="dev",
        dev_jwt_secret=DEV_SECRET,
        storage_provider="local",
        local_storage_dir=str(storage_dir),
    )

    async def get_test_db():
        async with _TestSessionFactory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app = create_app(settings=settings)
    app.dependency_overrides[get_db] = get_test_db
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def cleanup() -> None:
    yield
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from action_logs where user_id in (%s, %s)",
                (str(USER_A), str(USER_B)),
            )
            cur.execute("delete from documents where user_id in (%s, %s)", (USER_A, USER_B))
            cur.execute("delete from profiles where id in (%s, %s)", (USER_A, USER_B))
        conn.commit()


@pytest.fixture(autouse=True)
def clean_logs_before_each_test() -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "delete from action_logs where user_id in (%s, %s)",
                (str(USER_A), str(USER_B)),
            )
            cur.execute(
                "delete from documents where user_id in (%s, %s)",
                (str(USER_A), str(USER_B)),
            )
        conn.commit()
    yield


def _seed_user(user: uuid.UUID) -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into auth.users (id) values (%s) on conflict (id) do nothing",
                (user,),
            )
            cur.execute(
                "insert into profiles (id, email) values (%s, %s) "
                "on conflict (id) do nothing",
                (user, f"{user}@example.com"),
            )
        conn.commit()


def _insert_event(
    *,
    user_id: uuid.UUID,
    action_type: str,
    filename: str = "refund-policy.pdf",
    outcome: str = "succeeded",
    error_message: str | None = None,
    error_trace: str | None = None,
    metadata: dict | None = None,
    created_at: datetime | None = None,
) -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into action_logs "
                "(user_id, action_type, filename, outcome, error_message, "
                " error_trace, metadata, created_at) "
                "values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
                (
                    str(user_id),
                    action_type,
                    filename,
                    outcome,
                    error_message,
                    error_trace,
                    json.dumps(metadata) if metadata is not None else "{}",
                    created_at or datetime.now(timezone.utc),
                ),
            )
        conn.commit()


def _list(client: TestClient, token: str, **params) -> tuple[int, list | dict]:
    query = {"from" if k == "from_" else k: v for k, v in params.items()}
    response = client.get(
        "/api/v1/logs",
        headers={"Authorization": f"Bearer {token}"},
        params=query,
    )
    return response.status_code, response.json()


# ---------------------------------------------------------------------------
# US2: list endpoint
# ---------------------------------------------------------------------------


def test_logs_missing_auth_401(client: TestClient) -> None:
    assert client.get("/api/v1/logs").status_code == 401


def test_logs_empty_list_200(client: TestClient) -> None:
    _seed_user(USER_A)
    status, body = _list(client, _token(USER_A))
    assert status == 200
    assert body == []


def test_logs_newest_first_with_id_tiebreak(client: TestClient) -> None:
    _seed_user(USER_A)
    base = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    _insert_event(user_id=USER_A, action_type="upload", created_at=base)
    _insert_event(user_id=USER_A, action_type="delete", created_at=base + timedelta(seconds=5))
    _insert_event(user_id=USER_A, action_type="upload", created_at=base + timedelta(seconds=5))

    status, body = _list(client, _token(USER_A))
    assert status == 200
    assert len(body) == 3
    ids = [entry["id"] for entry in body]

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id from action_logs where user_id = %s order by created_at desc, id desc",
                (str(USER_A),),
            )
            expected = [row[0] for row in cur.fetchall()]
    assert ids == [str(e) for e in expected]
    assert body[0]["action_type"] == "delete" or body[0]["action_type"] == "upload"


def test_logs_paging_offset_limit_default_50(client: TestClient) -> None:
    _seed_user(USER_A)
    base = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        _insert_event(
            user_id=USER_A,
            action_type="upload",
            created_at=base + timedelta(minutes=i),
        )

    status, first_page = _list(client, _token(USER_A), limit=2)
    assert status == 200
    assert len(first_page) == 2
    status, second_page = _list(client, _token(USER_A), offset=2, limit=2)
    assert status == 200
    assert len(second_page) == 2
    status, last_page = _list(client, _token(USER_A), offset=4, limit=2)
    assert status == 200
    assert len(last_page) == 1
    assert len({e["id"] for e in first_page + second_page + last_page}) == 5


def test_logs_paging_bounds_422(client: TestClient) -> None:
    _seed_user(USER_A)
    token = _token(USER_A)
    assert _list(client, token, offset=-1)[0] == 422
    assert _list(client, token, limit=0)[0] == 422
    assert _list(client, token, limit=101)[0] == 422


def test_logs_payload_shape(client: TestClient) -> None:
    _seed_user(USER_A)
    _insert_event(
        user_id=USER_A,
        action_type="processing_failed",
        filename="broken.pdf",
        outcome="failed",
        error_message="PDF parse failed",
        error_trace="Traceback (most recent call last):\n  boom",
        metadata={"retry_count": 2},
    )
    status, body = _list(client, _token(USER_A))
    assert status == 200
    entry = body[0]
    assert set(entry) == {
        "id",
        "action_type",
        "outcome",
        "filename",
        "document_id",
        "error_message",
        "error_trace",
        "metadata",
        "created_at",
    }
    assert "user_id" not in entry
    assert "storage_path" not in entry
    assert entry["action_type"] == "processing_failed"
    assert entry["outcome"] == "failed"
    assert entry["error_message"] == "PDF parse failed"
    assert entry["error_trace"].startswith("Traceback")
    assert entry["metadata"] == {"retry_count": 2}


def test_logs_foreign_rows_invisible(client: TestClient) -> None:
    _seed_user(USER_A)
    _seed_user(USER_B)
    _insert_event(user_id=USER_B, action_type="upload", filename="secret.pdf")
    _insert_event(user_id=USER_B, action_type="delete", filename="secret.pdf")

    status, body = _list(client, _token(USER_A))
    assert status == 200
    assert body == []

    status, body = _list(client, _token(USER_B))
    assert status == 200
    assert len(body) == 2


# ---------------------------------------------------------------------------
# US3: filters
# ---------------------------------------------------------------------------


def test_logs_filter_action_type(client: TestClient) -> None:
    _seed_user(USER_A)
    _insert_event(user_id=USER_A, action_type="upload")
    _insert_event(user_id=USER_A, action_type="delete")

    status, body = _list(client, _token(USER_A), action_type="delete")
    assert status == 200
    assert [e["action_type"] for e in body] == ["delete"]


def test_logs_filter_from_to_inclusive(client: TestClient) -> None:
    _seed_user(USER_A)
    _insert_event(
        user_id=USER_A, action_type="upload",
        created_at=datetime(2026, 8, 1, 23, 59, 59, tzinfo=timezone.utc),
    )
    _insert_event(
        user_id=USER_A, action_type="upload",
        created_at=datetime(2026, 8, 2, 0, 0, 0, tzinfo=timezone.utc),
    )
    _insert_event(
        user_id=USER_A, action_type="upload",
        created_at=datetime(2026, 8, 3, 0, 0, 0, tzinfo=timezone.utc),
    )

    status, body = _list(client, _token(USER_A), from_="2026-08-02", to="2026-08-02")
    assert status == 200
    assert len(body) == 1
    created = datetime.fromisoformat(body[0]["created_at"])
    assert created == datetime(2026, 8, 2, 0, 0, 0, tzinfo=timezone.utc)

    status, body = _list(client, _token(USER_A), from_="2026-08-01", to="2026-08-03T00:00:00Z")
    assert status == 200
    assert len(body) == 3


def test_logs_filter_combined(client: TestClient) -> None:
    _seed_user(USER_A)
    day = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    _insert_event(user_id=USER_A, action_type="upload", created_at=day)
    _insert_event(user_id=USER_A, action_type="delete", created_at=day)
    _insert_event(
        user_id=USER_A, action_type="upload",
        created_at=day + timedelta(days=1),
    )

    status, body = _list(
        client, _token(USER_A), action_type="upload", from_="2026-08-10", to="2026-08-10"
    )
    assert status == 200
    assert len(body) == 1
    assert body[0]["action_type"] == "upload"


def test_logs_filter_unknown_action_type_422(client: TestClient) -> None:
    _seed_user(USER_A)
    assert _list(client, _token(USER_A), action_type="banana")[0] == 422


def test_logs_filter_malformed_dates_422(client: TestClient) -> None:
    _seed_user(USER_A)
    token = _token(USER_A)
    assert _list(client, token, from_="not-a-date")[0] == 422
    assert _list(client, token, to="08/20/2026")[0] == 422


def test_logs_filter_to_before_from_422(client: TestClient) -> None:
    _seed_user(USER_A)
    assert _list(client, _token(USER_A), from_="2026-08-20", to="2026-08-01")[0] == 422


def test_logs_filter_offset_limit_preserved(client: TestClient) -> None:
    _seed_user(USER_A)
    base = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(4):
        _insert_event(
            user_id=USER_A, action_type="upload", created_at=base + timedelta(minutes=i)
        )
    status, body = _list(client, _token(USER_A), action_type="upload", offset=1, limit=2)
    assert status == 200
    assert len(body) == 2

# ---------------------------------------------------------------------------
# US4: entry details round-trip (FR-010)
# ---------------------------------------------------------------------------


def test_logs_failed_entry_error_fields_round_trip(client: TestClient) -> None:
    _seed_user(USER_A)
    long_trace = "Traceback (most recent call last):\n" + "  boom\n" * 3000
    _insert_event(
        user_id=USER_A,
        action_type="processing_failed",
        filename="broken.pdf",
        outcome="failed",
        error_message="corrupt xref table",
        error_trace=long_trace,
        metadata={"retry_count": 3},
    )
    status, body = _list(client, _token(USER_A))
    assert status == 200
    entry = body[0]
    assert entry["outcome"] == "failed"
    assert entry["error_message"] == "corrupt xref table"
    assert entry["error_trace"] == long_trace
    assert len(entry["error_trace"]) > 8000  # full trace survived the payload
    assert entry["metadata"] == {"retry_count": 3}


def test_logs_success_entries_carry_no_error_fields(client: TestClient) -> None:
    _seed_user(USER_A)
    _insert_event(user_id=USER_A, action_type="upload")
    status, body = _list(client, _token(USER_A))
    assert status == 200
    entry = body[0]
    assert entry["outcome"] == "succeeded"
    assert entry["error_message"] is None
    assert entry["error_trace"] is None
