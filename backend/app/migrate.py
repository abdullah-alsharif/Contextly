"""Numbered-SQL migrations runner (python -m app.migrate).

Connects via DATABASE_URL, ensures a schema_migrations ledger, applies unapplied
files matching ^(\\d+)_.*\\.sql$ in ascending numeric order — each in its own
transaction — and no-ops cleanly when the directory is empty (research.md D4).
"""

import logging
import re
from pathlib import Path

from psycopg import Connection, connect

from app.core.config import get_settings

logger = logging.getLogger(__name__)

MIGRATION_RE = re.compile(r"^(\d+)_.*\.sql$")

LEDGER_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def _migrations(migrations_dir: Path) -> list[Path]:
    """Numbered SQL files, ascending numeric-prefix order."""
    if not migrations_dir.is_dir():
        return []
    numbered: list[tuple[int, Path]] = []
    for path in migrations_dir.iterdir():
        match = MIGRATION_RE.match(path.name)
        if path.is_file() and match:
            numbered.append((int(match.group(1)), path))
    numbered.sort(key=lambda item: item[0])
    return [path for _, path in numbered]


def _applied_filenames(conn: Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def apply_migrations(migrations_dir: Path, database_url: str) -> int:
    applied = 0
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(LEDGER_SQL)
        conn.commit()

        already = _applied_filenames(conn)
        for path in _migrations(migrations_dir):
            if path.name in already:
                continue
            sql = path.read_text()
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)",
                    (path.name,),
                )
            conn.commit()
            applied += 1
            logger.info("applied %s", path.name)
    return applied


def main() -> None:
    settings = get_settings()
    migrations_dir = Path(settings.migrations_dir)
    applied = apply_migrations(migrations_dir, settings.database_url)
    print(f"applied {applied} migration(s)")


if __name__ == "__main__":
    main()
