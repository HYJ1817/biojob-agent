"""Parameterized SQLite statements for BioJob domain services."""

from __future__ import annotations

import sqlite3


class BioJobRepository:
    """Execute BioJob SQL against a caller-owned connection and transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def insert_profile_fact(
        self,
        *,
        fact_id: str,
        category: str,
        fact_key: str,
        value_json: str,
        source_type: str,
        source_ref: str | None,
        status: str,
        visibility: str,
        confirmed_at: str | None,
        created_at: str,
        updated_at: str,
    ) -> None:
        self.connection.execute(
            "INSERT INTO profile_facts "
            "(id, category, fact_key, value_json, source_type, source_ref, status, "
            "visibility, confirmed_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fact_id,
                category,
                fact_key,
                value_json,
                source_type,
                source_ref,
                status,
                visibility,
                confirmed_at,
                created_at,
                updated_at,
            ),
        )

    def get_profile_fact(self, fact_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM profile_facts WHERE id = ?",
            (fact_id,),
        ).fetchone()

    def update_profile_fact_status(
        self,
        *,
        fact_id: str,
        status: str,
        confirmed_at: str | None,
        updated_at: str,
    ) -> int:
        cursor = self.connection.execute(
            "UPDATE profile_facts "
            "SET status = ?, confirmed_at = ?, updated_at = ? WHERE id = ?",
            (status, confirmed_at, updated_at, fact_id),
        )
        return cursor.rowcount

    def list_usable_profile_facts(
        self,
        *,
        status: str,
        first_visibility: str,
        second_visibility: str,
    ) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM profile_facts "
            "WHERE status = ? AND visibility IN (?, ?) "
            "ORDER BY created_at, id",
            (status, first_visibility, second_visibility),
        ).fetchall()

    def insert_audit_log(
        self,
        *,
        audit_id: str,
        action: str,
        entity_type: str,
        entity_id: str,
        actor: str,
        metadata_json: str,
        created_at: str,
    ) -> None:
        self.connection.execute(
            "INSERT INTO audit_log "
            "(id, action, entity_type, entity_id, actor, metadata_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                audit_id,
                action,
                entity_type,
                entity_id,
                actor,
                metadata_json,
                created_at,
            ),
        )

    def list_audit_log(self, entity_id: str | None = None) -> list[sqlite3.Row]:
        if entity_id is None:
            return self.connection.execute(
                "SELECT * FROM audit_log ORDER BY created_at, rowid"
            ).fetchall()
        return self.connection.execute(
            "SELECT * FROM audit_log WHERE entity_id = ? ORDER BY created_at, rowid",
            (entity_id,),
        ).fetchall()

    def upsert_company(
        self,
        *,
        company_id: str,
        canonical_name: str,
        company_type: str | None,
        city: str | None,
        aliases_json: str,
        created_at: str,
        updated_at: str,
    ) -> sqlite3.Row:
        self.connection.execute(
            "INSERT INTO companies "
            "(id, canonical_name, company_type, city, aliases_json, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(canonical_name) DO UPDATE SET "
            "company_type = COALESCE(NULLIF(companies.company_type, ''), "
            "excluded.company_type), "
            "city = COALESCE(NULLIF(companies.city, ''), excluded.city), "
            "updated_at = excluded.updated_at",
            (
                company_id,
                canonical_name,
                company_type,
                city,
                aliases_json,
                created_at,
                updated_at,
            ),
        )
        row = self.connection.execute(
            "SELECT * FROM companies WHERE canonical_name = ?",
            (canonical_name,),
        ).fetchone()
        if row is None:
            raise RuntimeError("upserted company could not be read back")
        return row

    def insert_job(
        self,
        *,
        job_id: str,
        company_id: str,
        title: str,
        direction: str | None,
        city: str | None,
        recruitment_type: str | None,
        education_requirement: str | None,
        major_requirement: str | None,
        jd_text: str | None,
        detail_url: str | None,
        apply_url: str | None,
        careers_url: str | None,
        published_at: str | None,
        deadline_at: str | None,
        lifecycle_status: str,
        notes: str,
        created_at: str,
        updated_at: str,
    ) -> None:
        self.connection.execute(
            "INSERT INTO jobs "
            "(id, company_id, title, direction, city, recruitment_type, "
            "education_requirement, major_requirement, jd_text, detail_url, "
            "apply_url, careers_url, published_at, deadline_at, lifecycle_status, "
            "notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                company_id,
                title,
                direction,
                city,
                recruitment_type,
                education_requirement,
                major_requirement,
                jd_text,
                detail_url,
                apply_url,
                careers_url,
                published_at,
                deadline_at,
                lifecycle_status,
                notes,
                created_at,
                updated_at,
            ),
        )

    def insert_application(
        self,
        *,
        application_id: str,
        job_id: str,
        status: str,
        applied_at: str | None,
        next_follow_up_at: str | None,
        notes: str,
        created_at: str,
        updated_at: str,
    ) -> None:
        self.connection.execute(
            "INSERT INTO applications "
            "(id, job_id, status, applied_at, next_follow_up_at, notes, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                application_id,
                job_id,
                status,
                applied_at,
                next_follow_up_at,
                notes,
                created_at,
                updated_at,
            ),
        )

    def insert_application_event(
        self,
        *,
        event_id: str,
        application_id: str,
        actor: str,
        old_status: str | None,
        new_status: str,
        note: str,
        created_at: str,
    ) -> None:
        self.connection.execute(
            "INSERT INTO application_events "
            "(id, application_id, actor, old_status, new_status, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                application_id,
                actor,
                old_status,
                new_status,
                note,
                created_at,
            ),
        )

    def get_job(self, job_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            _JOB_WITH_APPLICATION_SELECT
            + " WHERE jobs.id = ? AND jobs.deleted_at IS NULL",
            (job_id,),
        ).fetchone()

    def list_jobs(self) -> list[sqlite3.Row]:
        return self.connection.execute(
            _JOB_WITH_APPLICATION_SELECT + " WHERE jobs.deleted_at IS NULL "
            "ORDER BY jobs.created_at DESC, jobs.rowid DESC"
        ).fetchall()

    def update_application_status(
        self,
        *,
        application_id: str,
        status: str,
        applied_at: str | None,
        updated_at: str,
    ) -> int:
        cursor = self.connection.execute(
            "UPDATE applications SET status = ?, "
            "applied_at = COALESCE(applied_at, ?), updated_at = ? WHERE id = ?",
            (status, applied_at, updated_at, application_id),
        )
        return cursor.rowcount

    def update_job_fields(
        self,
        *,
        job_id: str,
        values: dict[str, str | None],
        updated_at: str,
    ) -> int:
        allowed = {
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
        }
        if not values or not set(values) <= allowed:
            raise ValueError("invalid job update fields")
        fields = (
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
        )
        parameters: list[str | int | None] = []
        for field in fields:
            parameters.extend((int(field in values), values.get(field)))
        parameters.extend((updated_at, job_id))
        cursor = self.connection.execute(
            "UPDATE jobs SET "
            "title = CASE WHEN ? THEN ? ELSE title END, "
            "direction = CASE WHEN ? THEN ? ELSE direction END, "
            "city = CASE WHEN ? THEN ? ELSE city END, "
            "recruitment_type = CASE WHEN ? THEN ? ELSE recruitment_type END, "
            "education_requirement = CASE WHEN ? THEN ? "
            "ELSE education_requirement END, "
            "major_requirement = CASE WHEN ? THEN ? ELSE major_requirement END, "
            "jd_text = CASE WHEN ? THEN ? ELSE jd_text END, "
            "detail_url = CASE WHEN ? THEN ? ELSE detail_url END, "
            "apply_url = CASE WHEN ? THEN ? ELSE apply_url END, "
            "careers_url = CASE WHEN ? THEN ? ELSE careers_url END, "
            "published_at = CASE WHEN ? THEN ? ELSE published_at END, "
            "deadline_at = CASE WHEN ? THEN ? ELSE deadline_at END, "
            "lifecycle_status = CASE WHEN ? THEN ? ELSE lifecycle_status END, "
            "notes = CASE WHEN ? THEN ? ELSE notes END, updated_at = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            parameters,
        )
        return cursor.rowcount

    def update_application_fields(
        self,
        *,
        application_id: str,
        values: dict[str, str | None],
        updated_at: str,
    ) -> int:
        allowed = {"next_follow_up_at", "notes"}
        if not values or not set(values) <= allowed:
            raise ValueError("invalid application update fields")
        cursor = self.connection.execute(
            "UPDATE applications SET "
            "next_follow_up_at = CASE WHEN ? THEN ? ELSE next_follow_up_at END, "
            "notes = CASE WHEN ? THEN ? ELSE notes END, updated_at = ? WHERE id = ?",
            (
                int("next_follow_up_at" in values),
                values.get("next_follow_up_at"),
                int("notes" in values),
                values.get("notes"),
                updated_at,
                application_id,
            ),
        )
        return cursor.rowcount

    def soft_delete_job(self, *, job_id: str, deleted_at: str) -> int:
        cursor = self.connection.execute(
            "UPDATE jobs SET deleted_at = ?, updated_at = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            (deleted_at, deleted_at, job_id),
        )
        return cursor.rowcount

    def list_application_events(self, job_id: str) -> list[sqlite3.Row] | None:
        active = self.connection.execute(
            "SELECT 1 FROM jobs WHERE id = ? AND deleted_at IS NULL",
            (job_id,),
        ).fetchone()
        if active is None:
            return None
        return self.connection.execute(
            "SELECT application_events.* FROM application_events "
            "JOIN applications ON applications.id = application_events.application_id "
            "WHERE applications.job_id = ? "
            "ORDER BY application_events.created_at, application_events.rowid",
            (job_id,),
        ).fetchall()

    def dashboard_counts(self) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT applications.id, applications.status FROM applications "
            "JOIN jobs ON jobs.id = applications.job_id "
            "WHERE jobs.deleted_at IS NULL "
            "ORDER BY applications.status, applications.id"
        ).fetchall()


_JOB_WITH_APPLICATION_SELECT = """
SELECT
    jobs.*,
    companies.canonical_name AS company_name,
    companies.company_type AS company_company_type,
    companies.city AS company_city,
    applications.id AS application_id,
    applications.status AS application_status,
    applications.applied_at AS application_applied_at,
    applications.next_follow_up_at AS application_next_follow_up_at,
    applications.notes AS application_notes,
    applications.created_at AS application_created_at,
    applications.updated_at AS application_updated_at
FROM jobs
JOIN companies ON companies.id = jobs.company_id
JOIN applications ON applications.job_id = jobs.id
"""
