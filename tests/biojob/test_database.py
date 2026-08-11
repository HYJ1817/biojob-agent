from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from biojob.database import BioJobDatabase
from biojob.paths import biojob_data_dir, biojob_database_path


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
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


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
