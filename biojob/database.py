"""SQLite connection and migration management for BioJob."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from biojob.paths import biojob_database_path
from biojob.schema import MIGRATIONS


_CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
)
"""


class BioJobDatabase:
    """Own BioJob SQLite connections and ordered schema migrations."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else biojob_database_path()

    def connect(self) -> sqlite3.Connection:
        """Open a configured SQLite connection for this database."""
        conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA journal_mode=WAL")
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
                conn.execute("ROLLBACK")
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
