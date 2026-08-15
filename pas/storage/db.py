"""SQLite access and migration runner.

Deliberately plain ``sqlite3``: the data model is relational and modest, and an
ORM would add a dependency without removing any real work here.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..config import DB_PATH, ensure_data_dir

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_local = threading.local()


def _configure(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    # Foreign keys are off by default in sqlite; without this the cascade rules
    # in the schema would be decorative.
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets the Streamlit UI read while a background analysis writes.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Return a thread-local connection.

    Streamlit reruns and the background job runner live on different threads,
    and sqlite connections are not shareable across them.
    """
    path = Path(db_path) if db_path else DB_PATH
    key = f"conn::{path}"
    conn = getattr(_local, key, None)
    if conn is None:
        ensure_data_dir()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
        _configure(conn)
        setattr(_local, key, conn)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a unit of work atomically."""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    conn.commit()
    return {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}


def split_statements(script: str) -> list[str]:
    """Split a SQL script into individual statements.

    ``sqlite3.complete_statement`` understands string literals and nested
    BEGIN...END blocks, so this is safe where naive splitting on ";" is not.
    """
    statements: list[str] = []
    buffer = ""

    for line in script.splitlines():
        stripped = line.strip()
        # Skip whole-line comments so a trailing comment cannot look like an
        # incomplete statement.
        if not stripped or stripped.startswith("--"):
            continue
        buffer += line + "\n"
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""

    if buffer.strip():
        statements.append(buffer.strip())
    return statements


def migrate(conn: sqlite3.Connection | None = None, db_path: Path | None = None) -> list[str]:
    """Apply any pending migrations atomically. Returns the names applied.

    Statements are executed individually rather than via ``executescript``,
    which issues an implicit COMMIT and would silently defeat the surrounding
    transaction - leaving a failed migration half-applied and unable to re-run.
    """
    from datetime import datetime, timezone

    conn = conn or get_connection(db_path)
    applied = _applied_versions(conn)
    executed: list[str] = []

    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(sql_file.stem.split("_", 1)[0])
        if version in applied:
            continue

        statements = split_statements(sql_file.read_text(encoding="utf-8"))

        # Python's sqlite3 opens implicit transactions for DML only - DDL runs
        # in autocommit, so a CREATE TABLE would survive a rollback. Manual
        # transaction control is required to make schema changes atomic.
        # SQLite itself supports transactional DDL; the driver is the obstacle.
        previous_isolation = conn.isolation_level
        conn.isolation_level = None
        try:
            conn.execute("BEGIN")
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, sql_file.name, datetime.now(timezone.utc).isoformat()),
            )
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:  # pragma: no cover - nothing to roll back
                pass
            raise
        finally:
            conn.isolation_level = previous_isolation

        executed.append(sql_file.name)

    return executed


def reset_thread_state() -> None:
    """Drop cached connections. Used by tests between temp databases."""
    for key in list(vars(_local)):
        conn = getattr(_local, key)
        if isinstance(conn, sqlite3.Connection):
            conn.close()
        delattr(_local, key)
