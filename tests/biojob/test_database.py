from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

import biojob.database as database_module
from biojob.database import BioJobDatabase
from biojob.paths import biojob_data_dir, biojob_database_path
from biojob.schema import MIGRATIONS


EXPECTED_COLUMNS = {
    "schema_migrations": {"version", "applied_at"},
    "profile_facts": {
        "id",
        "category",
        "fact_key",
        "value_json",
        "source_type",
        "source_ref",
        "status",
        "visibility",
        "confirmed_at",
        "created_at",
        "updated_at",
    },
    "profile_documents": {
        "id",
        "document_type",
        "original_name",
        "local_path",
        "sha256",
        "created_at",
    },
    "companies": {
        "id",
        "canonical_name",
        "company_type",
        "city",
        "aliases_json",
        "created_at",
        "updated_at",
    },
    "sources": {
        "id",
        "name",
        "adapter_type",
        "enabled",
        "health_status",
        "last_checked_at",
        "created_at",
        "updated_at",
    },
    "source_runs": {
        "id",
        "source_id",
        "status",
        "cursor_json",
        "result_count",
        "error_summary",
        "started_at",
        "finished_at",
    },
    "jobs": {
        "id",
        "company_id",
        "title",
        "direction",
        "city",
        "recruitment_type",
        "education_requirement",
        "major_requirement",
        "jd_text",
        "detail_url",
        "apply_url",
        "careers_url",
        "published_at",
        "deadline_at",
        "lifecycle_status",
        "notes",
        "created_at",
        "updated_at",
        "deleted_at",
    },
    "job_sources": {
        "id",
        "job_id",
        "source_id",
        "external_id",
        "detail_url",
        "apply_url",
        "careers_url",
        "first_seen_at",
        "last_seen_at",
        "is_active",
    },
    "job_snapshots": {
        "id",
        "job_source_id",
        "content_hash",
        "raw_jd",
        "fetched_at",
    },
    "job_matches": {
        "id",
        "job_id",
        "score",
        "recommendation",
        "evidence_json",
        "model_provider",
        "model_name",
        "rule_version",
        "created_at",
    },
    "candidate_decisions": {
        "id",
        "job_id",
        "decision",
        "actor",
        "note",
        "created_at",
    },
    "applications": {
        "id",
        "job_id",
        "status",
        "applied_at",
        "next_follow_up_at",
        "notes",
        "created_at",
        "updated_at",
    },
    "application_events": {
        "id",
        "application_id",
        "actor",
        "old_status",
        "new_status",
        "note",
        "created_at",
    },
    "resume_versions": {
        "id",
        "job_id",
        "file_path",
        "facts_json",
        "template_name",
        "content_hash",
        "created_at",
    },
    "scheduled_tasks": {
        "id",
        "task_type",
        "enabled",
        "schedule_json",
        "last_run_at",
        "next_run_at",
        "created_at",
        "updated_at",
    },
    "audit_log": {
        "id",
        "action",
        "entity_type",
        "entity_id",
        "actor",
        "metadata_json",
        "created_at",
    },
}

EXPECTED_INDEXES = {
    "idx_application_events_application_created",
    "idx_audit_log_entity_created",
    "idx_candidate_decisions_job_created",
    "idx_job_matches_job_created",
    "idx_source_runs_source_started",
}


def test_database_paths_follow_the_active_hermes_home(tmp_path, monkeypatch):
    first_home = tmp_path / "first-profile"
    second_home = tmp_path / "second-profile"

    monkeypatch.setenv("HERMES_HOME", str(first_home))
    assert biojob_data_dir() == first_home / "biojob"
    assert biojob_database_path() == first_home / "biojob" / "biojob.db"

    monkeypatch.setenv("HERMES_HOME", str(second_home))
    assert biojob_data_dir() == second_home / "biojob"
    assert biojob_database_path() == second_home / "biojob" / "biojob.db"


def test_initialize_creates_complete_schema_and_connection_pragmas(tmp_path):
    path = tmp_path / "nested" / "biojob.db"
    db = BioJobDatabase(path)

    db.initialize()

    assert path.is_file()
    with closing(db.connect()) as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert tables == set(EXPECTED_COLUMNS)
        for table, expected_columns in EXPECTED_COLUMNS.items():
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            assert columns == expected_columns

        assert conn.row_factory is sqlite3.Row
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() in {
            "wal",
            "delete",
        }


def test_connect_uses_the_shared_wal_fallback_result(tmp_path, monkeypatch):
    calls = []

    def use_delete_journal(conn, *, db_label, require_wal=False):
        row = conn.execute("PRAGMA journal_mode=DELETE").fetchone()
        mode = str(row[0]).lower()
        calls.append((db_label, require_wal, mode))
        return mode

    monkeypatch.setattr(
        database_module,
        "apply_wal_with_fallback",
        use_delete_journal,
    )
    db = BioJobDatabase(tmp_path / "biojob.db")

    db.initialize()

    with closing(db.connect()) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
    assert calls
    assert all(call == ("biojob.db", False, "delete") for call in calls)


def test_connect_retries_a_transient_wal_setup_lock(tmp_path, monkeypatch):
    attempts = 0

    def transient_lock_then_wal(conn, *, db_label, require_wal=False):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("database is locked")
        row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        return str(row[0]).lower()

    monkeypatch.setattr(
        database_module,
        "apply_wal_with_fallback",
        transient_lock_then_wal,
    )

    with closing(BioJobDatabase(tmp_path / "biojob.db").connect()) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert attempts == 2


def test_initialize_applies_migration_one_exactly_once(tmp_path):
    db = BioJobDatabase(tmp_path / "biojob.db")

    db.initialize()
    with closing(db.connect()) as conn:
        original = conn.execute(
            "SELECT version, applied_at FROM schema_migrations"
        ).fetchall()

    db.initialize()
    with closing(db.connect()) as conn:
        reapplied = conn.execute(
            "SELECT version, applied_at FROM schema_migrations"
        ).fetchall()

    assert [tuple(row) for row in original] == [(1, original[0]["applied_at"])]
    assert [tuple(row) for row in reapplied] == [tuple(original[0])]


def test_concurrent_initialize_applies_each_migration_once(tmp_path):
    path = tmp_path / "biojob.db"
    worker_count = 8
    start = threading.Barrier(worker_count, timeout=10)

    def initialize(_):
        start.wait()
        return BioJobDatabase(path).initialize()

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        initialized_paths = list(pool.map(initialize, range(worker_count)))

    assert initialized_paths == [path] * worker_count
    with closing(BioJobDatabase(path).connect()) as conn:
        versions = conn.execute(
            "SELECT version, COUNT(*) AS count "
            "FROM schema_migrations GROUP BY version"
        ).fetchall()
    assert [tuple(row) for row in versions] == [(1, 1)]


def test_failed_migration_rolls_back_every_statement_and_can_retry(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "biojob.db"
    db = BioJobDatabase(path)
    broken_migrations = MIGRATIONS + (
        (
            2,
            """
            CREATE TABLE migration_probe (id TEXT PRIMARY KEY);
            INSERT INTO migration_probe(id) VALUES ('before-failure');
            THIS IS NOT SQL;
            """,
        ),
    )
    monkeypatch.setattr(database_module, "MIGRATIONS", broken_migrations)

    with pytest.raises(sqlite3.OperationalError):
        db.initialize()

    with closing(sqlite3.connect(path)) as conn:
        tables_after_failure = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "migration_probe" not in tables_after_failure
    assert "schema_migrations" not in tables_after_failure

    monkeypatch.setattr(database_module, "MIGRATIONS", MIGRATIONS)
    db.initialize()
    with closing(db.connect()) as conn:
        versions = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert [tuple(row) for row in versions] == [(1,)]


def test_rollback_failure_does_not_hide_the_migration_error(tmp_path, monkeypatch):
    class RollbackFailingConnection:
        def __init__(self, delegate):
            self._delegate = delegate

        def execute(self, sql, *args):
            if sql.strip().upper() == "ROLLBACK":
                raise sqlite3.OperationalError("synthetic rollback failure")
            return self._delegate.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._delegate, name)

    db = BioJobDatabase(tmp_path / "biojob.db")
    real_connect = db.connect
    monkeypatch.setattr(
        db,
        "connect",
        lambda: RollbackFailingConnection(real_connect()),
    )
    monkeypatch.setattr(
        database_module,
        "MIGRATIONS",
        ((1, "THIS IS NOT SQL;"),),
    )

    with pytest.raises(sqlite3.OperationalError) as exc_info:
        db.initialize()

    assert "syntax error" in str(exc_info.value).lower()
    assert "rollback failure" not in str(exc_info.value).lower()


def test_schema_contains_relationship_query_indexes(tmp_path):
    db = BioJobDatabase(tmp_path / "biojob.db")
    db.initialize()

    with closing(db.connect()) as conn:
        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'index' AND name NOT LIKE 'sqlite_%'"
            )
        }

    assert EXPECTED_INDEXES <= indexes


def test_foreign_keys_and_check_constraints_are_enforced(tmp_path):
    db = BioJobDatabase(tmp_path / "biojob.db")
    db.initialize()

    with closing(db.connect()) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO source_runs "
                "(id, source_id, status, started_at) VALUES (?, ?, ?, ?)",
                ("run-1", "missing-source", "running", "2026-08-11T00:00:00+00:00"),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO profile_facts "
                "(id, category, fact_key, value_json, source_type, status, visibility, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "fact-1",
                    "laboratory",
                    "cell_culture",
                    "{}",
                    "user",
                    "invented",
                    "both",
                    "2026-08-11T00:00:00+00:00",
                    "2026-08-11T00:00:00+00:00",
                ),
            )


def test_schema_contains_no_credential_columns(tmp_path):
    db = BioJobDatabase(tmp_path / "biojob.db")
    db.initialize()

    forbidden_fragments = {"credential", "password", "secret", "api_key", "token"}
    with closing(db.connect()) as conn:
        column_names = {
            row["name"].lower()
            for table in EXPECTED_COLUMNS
            for row in conn.execute(f"PRAGMA table_info({table})")
        }

    assert all(
        fragment not in column_name
        for column_name in column_names
        for fragment in forbidden_fragments
    )
