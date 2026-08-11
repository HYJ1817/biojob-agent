from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone

import pytest

from biojob.database import BioJobDatabase
from biojob.schema import MIGRATIONS


def _create_version_one_database(path) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(MIGRATIONS[0][1])
        conn.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (1, datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            """
            INSERT INTO sources(
                id, name, adapter_type, enabled, health_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "source-existing",
                "Existing source",
                "manual",
                1,
                "unknown",
                "2026-08-12T00:00:00+00:00",
                "2026-08-12T00:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO companies(id, canonical_name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "company-existing",
                "Existing company",
                "2026-08-12T00:00:00+00:00",
                "2026-08-12T00:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO jobs(
                id, company_id, title, lifecycle_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "job-existing",
                "company-existing",
                "Existing role",
                "unknown",
                "2026-08-12T00:00:00+00:00",
                "2026-08-12T00:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO job_sources(
                id, job_id, source_id, external_id, detail_url,
                first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "job-source-existing",
                "job-existing",
                "source-existing",
                "external-existing",
                "https://example.test/jobs/existing",
                "2026-08-12T00:00:00+00:00",
                "2026-08-12T00:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO job_snapshots(
                id, job_source_id, content_hash, raw_jd, fetched_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "snapshot-existing",
                "job-source-existing",
                "hash-existing",
                "Existing JD",
                "2026-08-12T00:00:00+00:00",
            ),
        )
        conn.commit()


def _insert_job(conn, job_id: str, dedup_key: str, *, deleted_at=None) -> None:
    conn.execute(
        """
        INSERT INTO jobs(
            id, company_id, title, lifecycle_status, created_at, updated_at,
            deleted_at, dedup_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            "company-existing",
            "生物工艺技术员",
            "open",
            "2026-08-12T00:00:00+00:00",
            "2026-08-12T00:00:00+00:00",
            deleted_at,
            dedup_key,
        ),
    )


def test_migration_two_preserves_rows_and_adds_discovery_metadata(tmp_path):
    path = tmp_path / "biojob.db"
    _create_version_one_database(path)

    db = BioJobDatabase(path)
    db.initialize()
    db.initialize()

    with closing(db.connect()) as conn:
        versions = conn.execute(
            "SELECT version, COUNT(*) FROM schema_migrations GROUP BY version "
            "ORDER BY version"
        ).fetchall()
        assert [tuple(row) for row in versions] == [(1, 1), (2, 1), (3, 1)]

        source_columns = {
            row["name"]: row for row in conn.execute("PRAGMA table_info(sources)")
        }
        assert source_columns["config_json"]["notnull"] == 1
        assert source_columns["config_json"]["dflt_value"] == "'{}'"
        assert "description" in source_columns

        job_columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        assert "dedup_key" in job_columns
        assert (
            conn.execute(
                "SELECT name FROM sources WHERE id = ?", ("source-existing",)
            ).fetchone()[0]
            == "Existing source"
        )
        assert (
            conn.execute(
                "SELECT title FROM jobs WHERE id = ?", ("job-existing",)
            ).fetchone()[0]
            == "Existing role"
        )
        assert (
            conn.execute(
                "SELECT raw_jd FROM job_snapshots WHERE id = ?",
                ("snapshot-existing",),
            ).fetchone()[0]
            == "Existing JD"
        )


def test_active_dedup_key_is_unique_but_deleted_history_is_retained(tmp_path):
    db = BioJobDatabase(tmp_path / "biojob.db")
    db.initialize()

    with closing(db.connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO companies(id, canonical_name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                "company-existing",
                "齐鲁制药",
                "2026-08-12T00:00:00+00:00",
                "2026-08-12T00:00:00+00:00",
            ),
        )
        _insert_job(conn, "job-one", "qilu|生物工艺|济南|校招")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_job(conn, "job-two", "qilu|生物工艺|济南|校招")
        conn.execute(
            "UPDATE jobs SET deleted_at = ? WHERE id = ?",
            ("2026-08-12T01:00:00+00:00", "job-one"),
        )
        _insert_job(conn, "job-replacement", "qilu|生物工艺|济南|校招")
        conn.execute("COMMIT")

        index_sql = conn.execute(
            "SELECT sql FROM sqlite_schema WHERE type='index' AND name=?",
            ("idx_jobs_active_dedup_key",),
        ).fetchone()[0]
        assert "WHERE dedup_key IS NOT NULL AND deleted_at IS NULL" in index_sql
