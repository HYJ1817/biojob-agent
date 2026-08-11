"""Ordered SQLite schema migrations for BioJob."""

from typing import Sequence


MIGRATIONS: Sequence[tuple[int, str]] = (
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS profile_facts (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            value_json TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_ref TEXT,
            status TEXT NOT NULL
                CHECK(status IN ('pending', 'confirmed', 'rejected', 'conflicted')),
            visibility TEXT NOT NULL
                CHECK(visibility IN ('matching', 'resume', 'both', 'private')),
            confirmed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(category, fact_key)
        );

        CREATE TABLE IF NOT EXISTS profile_documents (
            id TEXT PRIMARY KEY,
            document_type TEXT NOT NULL,
            original_name TEXT NOT NULL,
            local_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS companies (
            id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL UNIQUE,
            company_type TEXT,
            city TEXT,
            aliases_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            adapter_type TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            health_status TEXT NOT NULL DEFAULT 'unknown',
            last_checked_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS source_runs (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            status TEXT NOT NULL
                CHECK(status IN ('running', 'completed', 'failed', 'cancelled')),
            cursor_json TEXT NOT NULL DEFAULT '{}',
            result_count INTEGER NOT NULL DEFAULT 0,
            error_summary TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
            title TEXT NOT NULL,
            direction TEXT,
            city TEXT,
            recruitment_type TEXT,
            education_requirement TEXT,
            major_requirement TEXT,
            jd_text TEXT,
            detail_url TEXT,
            apply_url TEXT,
            careers_url TEXT,
            published_at TEXT,
            deadline_at TEXT,
            lifecycle_status TEXT NOT NULL DEFAULT 'unknown'
                CHECK(lifecycle_status IN ('open', 'closed', 'unknown')),
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT
        );

        CREATE TABLE IF NOT EXISTS job_sources (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
            external_id TEXT,
            detail_url TEXT,
            apply_url TEXT,
            careers_url TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(job_id, detail_url)
        );

        CREATE TABLE IF NOT EXISTS job_snapshots (
            id TEXT PRIMARY KEY,
            job_source_id TEXT NOT NULL REFERENCES job_sources(id) ON DELETE CASCADE,
            content_hash TEXT NOT NULL,
            raw_jd TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            UNIQUE(job_source_id, content_hash)
        );

        CREATE TABLE IF NOT EXISTS job_matches (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            score REAL NOT NULL CHECK(score >= 0 AND score <= 100),
            recommendation TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            model_provider TEXT,
            model_name TEXT,
            rule_version TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS candidate_decisions (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            decision TEXT NOT NULL
                CHECK(decision IN ('pending', 'kept', 'ignored', 'later', 'error')),
            actor TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS applications (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,
            status TEXT NOT NULL CHECK(status IN (
                'considering', 'preparing', 'applied', 'assessment', 'interview',
                'offer', 'rejected', 'withdrawn', 'expired'
            )),
            applied_at TEXT,
            next_follow_up_at TEXT,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS application_events (
            id TEXT PRIMARY KEY,
            application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
            actor TEXT NOT NULL,
            old_status TEXT,
            new_status TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS resume_versions (
            id TEXT PRIMARY KEY,
            job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
            file_path TEXT NOT NULL,
            facts_json TEXT NOT NULL,
            template_name TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id TEXT PRIMARY KEY,
            task_type TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            schedule_json TEXT NOT NULL,
            last_run_at TEXT,
            next_run_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id TEXT PRIMARY KEY,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            actor TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_source_runs_source_started
            ON source_runs(source_id, started_at);
        CREATE INDEX IF NOT EXISTS idx_jobs_company_created
            ON jobs(company_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_job_sources_source_last_seen
            ON job_sources(source_id, last_seen_at);
        CREATE INDEX IF NOT EXISTS idx_job_matches_job_created
            ON job_matches(job_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_candidate_decisions_job_created
            ON candidate_decisions(job_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_application_events_application_created
            ON application_events(application_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_resume_versions_job_created
            ON resume_versions(job_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_audit_log_entity_created
            ON audit_log(entity_id, created_at);
        """,
    ),
    (
        2,
        """
        ALTER TABLE sources
            ADD COLUMN config_json TEXT NOT NULL DEFAULT '{}';
        ALTER TABLE sources
            ADD COLUMN description TEXT;
        ALTER TABLE jobs
            ADD COLUMN dedup_key TEXT;

        CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_active_dedup_key
            ON jobs(dedup_key)
            WHERE dedup_key IS NOT NULL AND deleted_at IS NULL;
        """,
    ),
)
