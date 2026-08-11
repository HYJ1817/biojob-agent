"""SQLite connection and migration management for BioJob."""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from biojob.paths import biojob_database_path
from biojob.schema import MIGRATIONS
from hermes_state import apply_wal_with_fallback


_CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
)
"""

_JOURNAL_MODE_LOCK_TIMEOUT_SECONDS = 10.0
_JOURNAL_MODE_RETRY_DELAY_SECONDS = 0.05
_journal_mode_locks: dict[str, threading.Lock] = {}
_journal_mode_locks_guard = threading.Lock()


class BioJobDatabase:
    """Own BioJob SQLite connections and ordered schema migrations."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else biojob_database_path()

    def connect(self) -> sqlite3.Connection:
        """Open a configured SQLite connection for this database.

        WAL is preferred through Hermes' shared compatibility policy. The
        connection remains usable in DELETE mode when that policy detects an
        unsupported filesystem or protected SQLite version; unrelated setup
        errors still propagate.
        """
        conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            lock = _journal_mode_lock(self.path)
            if not lock.acquire(timeout=_JOURNAL_MODE_LOCK_TIMEOUT_SECONDS):
                raise sqlite3.OperationalError(
                    f"timed out configuring journal mode for {self.path}"
                )
            try:
                journal_mode = _apply_journal_mode(conn)
            finally:
                lock.release()
            if journal_mode not in {"wal", "delete"}:
                raise sqlite3.OperationalError(
                    f"unsupported BioJob journal mode: {journal_mode!r}"
                )
        except Exception:
            conn.close()
            raise
        return conn

    def initialize(self) -> Path:
        """Create the database and atomically apply every pending migration."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(_CREATE_MIGRATIONS_TABLE)
            applied = {
                row["version"]
                for row in conn.execute("SELECT version FROM schema_migrations")
            }
            for version, sql in MIGRATIONS:
                if version in applied:
                    continue
                _execute_migration(conn, sql)
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, datetime.now(timezone.utc).isoformat()),
                )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
            raise
        finally:
            conn.close()
        return self.path


def _execute_migration(conn: sqlite3.Connection, sql: str) -> None:
    """Execute a multi-statement migration without leaving its transaction."""
    statement = ""
    for line in sql.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("migration contains an incomplete SQL statement")


def _journal_mode_lock(path: Path) -> threading.Lock:
    """Return the process-local journal-mode setup lock for ``path``."""
    key = str(path.resolve())
    with _journal_mode_locks_guard:
        return _journal_mode_locks.setdefault(key, threading.Lock())


def _apply_journal_mode(conn: sqlite3.Connection) -> str:
    """Apply the shared WAL policy, retrying one transient lock conflict."""
    for attempt in range(2):
        try:
            return apply_wal_with_fallback(conn, db_label="biojob.db")
        except sqlite3.OperationalError as exc:
            locked = "locked" in str(exc).lower() or "busy" in str(exc).lower()
            if not locked or attempt == 1:
                raise
            time.sleep(_JOURNAL_MODE_RETRY_DELAY_SECONDS)
    raise AssertionError("unreachable")
