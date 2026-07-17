"""SQLite connection + schema bootstrap.

Migration strategy (single-user app, so this stays simple): the current
schema always lives in `schema.sql`, applied in full via `CREATE TABLE IF
NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` — safe to run against an
already-initialized database. Any change that isn't purely additive (rename,
drop, backfill) gets a numbered file in `migrations/NNN_description.sql`;
`get_connection` applies whichever of those haven't run yet, tracked by the
single row in `schema_version`.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_SCHEMA_SQL_PATH = Path(__file__).parent / "schema.sql"
_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

DEFAULT_DB_PATH = Path("data/nutriologist.db")


def _default_db_path() -> Path:
    return Path(os.environ.get("NUTRIOLOGIST_DB_PATH", DEFAULT_DB_PATH))


def _migration_files() -> list[Path]:
    if not _MIGRATIONS_DIR.is_dir():
        return []
    return sorted(_MIGRATIONS_DIR.glob("*.sql"))


def _current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    return row[0] if row else 0


def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL_PATH.read_text())

    if conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 0:
        conn.execute("INSERT INTO schema_version (version) VALUES (0)")

    version = _current_version(conn)
    for migration_path in _migration_files():
        migration_version = int(migration_path.stem.split("_", 1)[0])
        if migration_version <= version:
            continue
        conn.executescript(migration_path.read_text())
        conn.execute("UPDATE schema_version SET version = ?", (migration_version,))
        version = migration_version

    conn.commit()


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open (creating and migrating if needed) the nutriologist SQLite DB.

    Args:
        db_path: Defaults to `$NUTRIOLOGIST_DB_PATH` or `data/nutriologist.db`.
            Pass `":memory:"` for an ephemeral in-process database (tests).
    """
    path = Path(db_path) if db_path is not None else _default_db_path()
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _apply_schema(conn)
    return conn
