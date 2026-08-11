"""Transactional domain operations for the BioJob data core."""

from __future__ import annotations

from collections.abc import Mapping
import ipaddress
import hashlib
import json
import math
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from biojob.database import BioJobDatabase
from biojob.domain import (
    ApplicationStatus,
    CandidateDecision,
    DomainConflictError,
    DomainDataCorruptionError,
    DomainNotFoundError,
    DomainValidationError,
    FactVisibility,
    ProfileFactStatus,
    RawJob,
)
from biojob.repository import BioJobRepository
from biojob.matching import match_job as build_match_report
from biojob.documents import (
    MAX_PROFILE_DOCUMENT_BYTES,
    WORKBOOK_SHEETS,
    copy_profile_document,
    extract_profile_lines,
    write_application_workbook,
    write_resume_docx,
)
from biojob.sources.base import JobSourceAdapter
from biojob.sources.catalog import DEFAULT_SOURCES, default_adapter_registry


_APPLICATION_TRANSITIONS: dict[str, frozenset[str]] = {
    ApplicationStatus.CONSIDERING.value: frozenset({
        ApplicationStatus.PREPARING.value,
        ApplicationStatus.WITHDRAWN.value,
        ApplicationStatus.EXPIRED.value,
    }),
    ApplicationStatus.PREPARING.value: frozenset({
        ApplicationStatus.APPLIED.value,
        ApplicationStatus.REJECTED.value,
        ApplicationStatus.WITHDRAWN.value,
        ApplicationStatus.EXPIRED.value,
    }),
    ApplicationStatus.APPLIED.value: frozenset({
        ApplicationStatus.ASSESSMENT.value,
        ApplicationStatus.INTERVIEW.value,
        ApplicationStatus.OFFER.value,
        ApplicationStatus.REJECTED.value,
        ApplicationStatus.EXPIRED.value,
    }),
    ApplicationStatus.ASSESSMENT.value: frozenset({
        ApplicationStatus.INTERVIEW.value,
        ApplicationStatus.OFFER.value,
        ApplicationStatus.REJECTED.value,
        ApplicationStatus.EXPIRED.value,
    }),
    ApplicationStatus.INTERVIEW.value: frozenset({
        ApplicationStatus.OFFER.value,
        ApplicationStatus.REJECTED.value,
        ApplicationStatus.EXPIRED.value,
    }),
    ApplicationStatus.OFFER.value: frozenset(),
    ApplicationStatus.REJECTED.value: frozenset(),
    ApplicationStatus.WITHDRAWN.value: frozenset(),
    ApplicationStatus.EXPIRED.value: frozenset(),
}

_URL_FIELDS = {"detail_url", "apply_url", "careers_url"}
_DNS_LABEL_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_JOB_UPDATE_FIELDS = {
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

_MATCH_RULE_VERSION = "biojob-undergraduate-v1"
_POSITIVE_TERMS = (
    "生物工艺",
    "生产",
    "发酵",
    "细胞培养",
    "QA",
    "QC",
    "质量",
    "GMP",
    "实验员",
    "本科",
    "应届",
)
_HARD_GAP_TERMS = ("博士", "仅限硕士", "药物合成", "医药销售", "临床项目经理")


class BioJobService:
    """Coordinate profile-fact validation, transactions, and audit records."""

    def __init__(
        self,
        database: BioJobDatabase | None = None,
        *,
        source_adapters: Mapping[str, JobSourceAdapter] | None = None,
    ) -> None:
        self.database = database or BioJobDatabase()
        self.database.initialize()
        self.source_adapters = default_adapter_registry()
        if source_adapters is not None:
            self.source_adapters.update(source_adapters)

    def ensure_default_sources(self) -> list[dict[str, Any]]:
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            repository = BioJobRepository(connection)
            for default in DEFAULT_SOURCES:
                if (
                    repository.get_source_by_name(default.name) is not None
                    or repository.get_source(default.source_id) is not None
                ):
                    continue
                created_at = _utc_now()
                repository.insert_source(
                    source_id=default.source_id,
                    name=default.name,
                    adapter_type=default.adapter_type,
                    enabled=default.enabled,
                    config_json=_serialize_json("config", default.config),
                    description=default.description,
                    created_at=created_at,
                )
                self._insert_audit(
                    repository,
                    action="source.default_created",
                    entity_id=default.source_id,
                    entity_type="source",
                    actor="system",
                    metadata={"name": default.name},
                    created_at=created_at,
                )
            result = [_source_dict(row) for row in repository.list_sources()]
            connection.execute("COMMIT")
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()
        return result

    def list_sources(self) -> list[dict[str, Any]]:
        connection = self.database.connect()
        try:
            return [
                _source_dict(row) for row in BioJobRepository(connection).list_sources()
            ]
        finally:
            connection.close()

    def create_source(
        self,
        *,
        name: str,
        adapter_type: str,
        config: Mapping[str, object],
        actor: str,
        enabled: bool = True,
        description: str | None = None,
    ) -> dict[str, Any]:
        name = _require_nonempty_string("name", name)
        adapter_type = _require_nonempty_string("adapter_type", adapter_type)
        actor = _require_nonempty_string("actor", actor)
        if not isinstance(enabled, bool):
            raise DomainValidationError("enabled must be a boolean")
        if adapter_type not in self.source_adapters:
            raise DomainValidationError(f"unknown source adapter: {adapter_type}")
        config_value = _validate_source_config(adapter_type, config)
        description_value = _normalize_candidate_text("description", description)
        source_id = str(uuid4())
        created_at = _utc_now()
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            repository = BioJobRepository(connection)
            repository.insert_source(
                source_id=source_id,
                name=name,
                adapter_type=adapter_type,
                enabled=enabled,
                config_json=_serialize_json("config", config_value),
                description=description_value,
                created_at=created_at,
            )
            self._insert_audit(
                repository,
                action="source.created",
                entity_id=source_id,
                entity_type="source",
                actor=actor,
                metadata={"name": name, "adapter_type": adapter_type},
                created_at=created_at,
            )
            row = repository.get_source(source_id)
            if row is None:
                raise RuntimeError("created source could not be read back")
            result = _source_dict(row)
            connection.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            _rollback(connection)
            raise DomainConflictError(f"source already exists: {name}") from exc
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()
        return result

    def update_source(
        self,
        source_id: str,
        *,
        actor: str,
        name: str | None = None,
        enabled: bool | None = None,
        config: Mapping[str, object] | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        source_id = _require_nonempty_string("source_id", source_id)
        actor = _require_nonempty_string("actor", actor)
        fields = {
            key
            for key, value in {
                "name": name,
                "enabled": enabled,
                "config": config,
                "description": description,
            }.items()
            if value is not None
        }
        if not fields:
            raise DomainValidationError("source update must include at least one field")
        if enabled is not None and not isinstance(enabled, bool):
            raise DomainValidationError("enabled must be a boolean")
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            repository = BioJobRepository(connection)
            current_row = repository.get_source(source_id)
            if current_row is None:
                raise DomainNotFoundError(f"source not found: {source_id}")
            current = _source_dict(current_row)
            values: dict[str, str | int | None] = {}
            if name is not None:
                values["name"] = _require_nonempty_string("name", name)
            if enabled is not None:
                values["enabled"] = int(enabled)
            if config is not None:
                values["config_json"] = _serialize_json(
                    "config", _validate_source_config(current["adapter_type"], config)
                )
            if description is not None:
                values["description"] = _normalize_candidate_text(
                    "description", description
                )
            updated_at = _utc_now()
            repository.update_source(
                source_id=source_id, values=values, updated_at=updated_at
            )
            self._insert_audit(
                repository,
                action="source.updated",
                entity_id=source_id,
                entity_type="source",
                actor=actor,
                metadata={"fields": sorted(fields)},
                created_at=updated_at,
            )
            row = repository.get_source(source_id)
            if row is None:
                raise RuntimeError("updated source could not be read back")
            result = _source_dict(row)
            connection.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            _rollback(connection)
            raise DomainConflictError(
                "source update conflicts with existing data"
            ) from exc
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()
        return result

    def run_source(self, source_id: str, *, actor: str) -> dict[str, Any]:
        from biojob.discovery import DiscoveryRunner

        source_id = _require_nonempty_string("source_id", source_id)
        actor = _require_nonempty_string("actor", actor)
        connection = self.database.connect()
        try:
            row = BioJobRepository(connection).get_source(source_id)
            if row is None:
                raise DomainNotFoundError(f"source not found: {source_id}")
            source = _source_dict(row)
        finally:
            connection.close()
        if not source["enabled"]:
            raise DomainConflictError(f"source is disabled: {source_id}")
        if source["adapter_type"] not in self.source_adapters:
            raise DomainValidationError(
                f"unknown source adapter: {source['adapter_type']}"
            )
        run_id = DiscoveryRunner(self.database, self, self.source_adapters).run(
            source, actor=actor
        )
        connection = self.database.connect()
        try:
            run = BioJobRepository(connection).get_source_run(run_id)
            if run is None:
                raise RuntimeError("completed source run could not be read back")
            return _source_run_dict(run)
        finally:
            connection.close()

    def run_enabled_sources(self, *, actor: str) -> list[dict[str, Any]]:
        actor = _require_nonempty_string("actor", actor)
        connection = self.database.connect()
        try:
            source_ids = [
                row["id"]
                for row in BioJobRepository(connection).list_sources(enabled_only=True)
            ]
        finally:
            connection.close()
        return [self.run_source(source_id, actor=actor) for source_id in source_ids]

    def list_source_runs(self, *, source_id: str | None = None) -> list[dict[str, Any]]:
        if source_id is not None:
            source_id = _require_nonempty_string("source_id", source_id)
        connection = self.database.connect()
        try:
            rows = BioJobRepository(connection).list_source_runs(source_id)
            return [_source_run_dict(row) for row in rows]
        finally:
            connection.close()

    def import_candidate(self, raw_job: RawJob, *, actor: str) -> dict[str, Any]:
        actor = _require_nonempty_string("actor", actor)
        source_name = "手工导入"
        source_id = "manual-import"
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            repository = BioJobRepository(connection)
            row = repository.get_source_by_name(source_name)
            if row is None:
                conflicting_id = repository.get_source(source_id)
                if conflicting_id is not None:
                    raise DomainConflictError(
                        "manual import source identifier is already in use"
                    )
                created_at = _utc_now()
                repository.insert_source(
                    source_id=source_id,
                    name=source_name,
                    adapter_type="manual",
                    enabled=True,
                    config_json="{}",
                    description="用户手工导入的岗位，不执行网络请求。",
                    created_at=created_at,
                )
                self._insert_audit(
                    repository,
                    action="source.default_created",
                    entity_id=source_id,
                    entity_type="source",
                    actor=actor,
                    metadata={"name": source_name},
                    created_at=created_at,
                )
            else:
                source = _source_dict(row)
                source_id = source["id"]
                if source["adapter_type"] != "manual":
                    raise DomainConflictError(
                        "manual import source name belongs to another adapter"
                    )
            connection.execute("COMMIT")
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()
        return self.ingest_candidate(raw_job, source_id=source_id, actor=actor)

    def discovery_dashboard_counts(self) -> dict[str, dict[str, int]]:
        connection = self.database.connect()
        try:
            repository = BioJobRepository(connection)
            candidate_counts = {decision.value: 0 for decision in CandidateDecision}
            for row in repository.candidate_counts():
                decision = _parse_persisted_candidate_decision(
                    row["decision"], "dashboard"
                )
                candidate_counts[decision] = row["count"]
            source_row = repository.source_counts()
            source_counts = {
                key: source_row[key]
                for key in ("total", "enabled", "healthy", "degraded", "failed")
            }
            return {
                "candidate_counts": candidate_counts,
                "source_counts": source_counts,
            }
        finally:
            connection.close()

    def ingest_candidate(
        self,
        raw_job: RawJob,
        *,
        source_id: str,
        actor: str,
    ) -> dict[str, Any]:
        """Create or refresh a review candidate without creating an application."""
        if not isinstance(raw_job, RawJob):
            raise DomainValidationError("raw_job must be a RawJob")
        source_id = _require_nonempty_string("source_id", source_id)
        actor = _require_nonempty_string("actor", actor)
        company_name = _normalize_candidate_text(
            "company_name", raw_job.company_name, required=True
        )
        title = _normalize_candidate_text("title", raw_job.title, required=True)
        assert company_name is not None
        assert title is not None
        city = _normalize_candidate_text("city", raw_job.city)
        recruitment_type = _normalize_candidate_text(
            "recruitment_type", raw_job.recruitment_type
        )
        jd_text = _normalize_candidate_text("jd_text", raw_job.jd_text)
        external_id = _normalize_candidate_text("external_id", raw_job.external_id)
        published_at = _normalize_candidate_text("published_at", raw_job.published_at)
        deadline_at = _normalize_candidate_text("deadline_at", raw_job.deadline_at)
        detail_url = _normalize_url("detail_url", raw_job.detail_url)
        apply_url = _normalize_url("apply_url", raw_job.apply_url)
        careers_url = _normalize_url("careers_url", raw_job.careers_url)
        if detail_url is None:
            raise DomainValidationError("detail_url must be a non-empty URL")

        dedup_key = _candidate_dedup_key(company_name, title, city, recruitment_type)
        direction = _infer_candidate_direction(title, jd_text)
        snapshot_payload = {
            "company_name": company_name,
            "title": title,
            "city": city,
            "jd_text": jd_text,
            "detail_url": detail_url,
            "apply_url": apply_url,
            "careers_url": careers_url,
            "external_id": external_id,
            "published_at": published_at,
            "deadline_at": deadline_at,
            "recruitment_type": recruitment_type,
        }
        snapshot_json = _serialize_json("raw_job", snapshot_payload)
        content_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()

        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            repository = BioJobRepository(connection)
            if repository.get_source(source_id) is None:
                raise DomainNotFoundError(f"source not found: {source_id}")
            seen_at = _utc_now()
            job = repository.get_active_job_by_dedup_key(dedup_key)
            created = job is None
            if job is None:
                company = repository.upsert_company(
                    company_id=str(uuid4()),
                    canonical_name=company_name,
                    company_type=None,
                    city=city,
                    aliases_json=_serialize_json("aliases", []),
                    created_at=seen_at,
                    updated_at=seen_at,
                )
                job_id = str(uuid4())
                repository.insert_job(
                    job_id=job_id,
                    company_id=company["id"],
                    title=title,
                    direction=direction,
                    city=city,
                    recruitment_type=recruitment_type,
                    education_requirement=None,
                    major_requirement=None,
                    jd_text=jd_text,
                    detail_url=detail_url,
                    apply_url=apply_url,
                    careers_url=careers_url,
                    published_at=published_at,
                    deadline_at=deadline_at,
                    lifecycle_status="unknown",
                    notes="",
                    created_at=seen_at,
                    updated_at=seen_at,
                    dedup_key=dedup_key,
                )
            else:
                job_id = job["id"]
                repository.update_job_fields(
                    job_id=job_id,
                    values={
                        "title": title,
                        "direction": direction,
                        "city": city,
                        "recruitment_type": recruitment_type,
                        "jd_text": jd_text,
                        "detail_url": detail_url,
                        "apply_url": apply_url,
                        "careers_url": careers_url,
                        "published_at": published_at,
                        "deadline_at": deadline_at,
                    },
                    updated_at=seen_at,
                )
            job_source = repository.upsert_job_source(
                job_source_id=str(uuid4()),
                job_id=job_id,
                source_id=source_id,
                external_id=external_id,
                detail_url=detail_url,
                apply_url=apply_url,
                careers_url=careers_url,
                seen_at=seen_at,
            )
            snapshot_inserted = repository.insert_job_snapshot(
                snapshot_id=str(uuid4()),
                job_source_id=job_source["id"],
                content_hash=content_hash,
                raw_jd=jd_text or "",
                fetched_at=seen_at,
            )
            if snapshot_inserted:
                match = _screen_candidate(title=title, jd_text=jd_text)
                repository.insert_job_match(
                    match_id=str(uuid4()),
                    job_id=job_id,
                    score=match["score"],
                    recommendation=match["recommendation"],
                    evidence_json=_serialize_json("evidence", match["evidence"]),
                    model_provider=None,
                    model_name=None,
                    rule_version=_MATCH_RULE_VERSION,
                    created_at=seen_at,
                )
            if created:
                repository.insert_candidate_decision(
                    decision_id=str(uuid4()),
                    job_id=job_id,
                    decision=CandidateDecision.PENDING.value,
                    actor=actor,
                    note="",
                    created_at=seen_at,
                )
                self._insert_audit(
                    repository,
                    action="candidate.discovered",
                    entity_id=job_id,
                    entity_type="job",
                    actor=actor,
                    metadata={"source_id": source_id, "dedup_key": dedup_key},
                    created_at=seen_at,
                )
            elif snapshot_inserted:
                self._insert_audit(
                    repository,
                    action="candidate.refreshed",
                    entity_id=job_id,
                    entity_type="job",
                    actor=actor,
                    metadata={"source_id": source_id},
                    created_at=seen_at,
                )
            row = repository.get_candidate(job_id)
            if row is None:
                raise RuntimeError("ingested candidate could not be read back")
            result = _candidate_dict(row)
            connection.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            _rollback(connection)
            raise DomainConflictError(f"candidate ingestion conflict: {exc}") from None
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()
        return result

    def list_candidates(
        self,
        decision: str | CandidateDecision = CandidateDecision.PENDING,
        *,
        query: str | None = None,
        direction: str | None = None,
        city: str | None = None,
    ) -> list[dict[str, Any]]:
        decision_value = _parse_candidate_decision(decision)
        query = _normalize_candidate_text("query", query)
        direction = _normalize_candidate_text("direction", direction)
        city = _normalize_candidate_text("city", city)
        connection = self.database.connect()
        try:
            rows = BioJobRepository(connection).list_candidates(
                decision=decision_value,
                query=query,
                direction=direction,
                city=city,
            )
            return [_candidate_dict(row) for row in rows]
        finally:
            connection.close()

    def get_candidate(self, job_id: str) -> dict[str, Any]:
        job_id = _require_nonempty_string("job_id", job_id)
        connection = self.database.connect()
        try:
            row = BioJobRepository(connection).get_candidate(job_id)
            if row is None:
                raise DomainNotFoundError(f"candidate not found: {job_id}")
            return _candidate_dict(row)
        finally:
            connection.close()

    def decide_candidate(
        self,
        job_id: str,
        decision: str | CandidateDecision,
        *,
        actor: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        job_id = _require_nonempty_string("job_id", job_id)
        actor = _require_nonempty_string("actor", actor)
        decision_value = _parse_candidate_decision(decision)
        note_value = "" if note is None else _normalize_notes("note", note)
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            repository = BioJobRepository(connection)
            row = repository.get_candidate(job_id)
            if row is None:
                raise DomainNotFoundError(f"candidate not found: {job_id}")
            current = _candidate_dict(row)
            current_decision = current["decision"]
            allowed = (
                {CandidateDecision.PENDING.value}
                if current_decision == CandidateDecision.LATER.value
                else {
                    CandidateDecision.KEPT.value,
                    CandidateDecision.IGNORED.value,
                    CandidateDecision.LATER.value,
                    CandidateDecision.ERROR.value,
                }
                if current_decision == CandidateDecision.PENDING.value
                else set()
            )
            if decision_value not in allowed:
                raise DomainConflictError(
                    f"cannot change candidate decision from {current_decision!r} "
                    f"to {decision_value!r}"
                )
            decided_at = _utc_now()
            repository.insert_candidate_decision(
                decision_id=str(uuid4()),
                job_id=job_id,
                decision=decision_value,
                actor=actor,
                note=note_value,
                created_at=decided_at,
            )
            application_id = None
            if decision_value == CandidateDecision.KEPT.value:
                if current["application"] is not None:
                    raise DomainConflictError("candidate already has an application")
                application_id = str(uuid4())
                initial_status = ApplicationStatus.CONSIDERING.value
                repository.insert_application(
                    application_id=application_id,
                    job_id=job_id,
                    status=initial_status,
                    applied_at=None,
                    next_follow_up_at=None,
                    notes=note_value,
                    created_at=decided_at,
                    updated_at=decided_at,
                )
                repository.insert_application_event(
                    event_id=str(uuid4()),
                    application_id=application_id,
                    actor=actor,
                    old_status=None,
                    new_status=initial_status,
                    note=note_value,
                    created_at=decided_at,
                )
            self._insert_audit(
                repository,
                action="candidate.decided",
                entity_id=job_id,
                entity_type="job",
                actor=actor,
                metadata={
                    "old_decision": current_decision,
                    "new_decision": decision_value,
                    "note": note_value,
                    "application_id": application_id,
                },
                created_at=decided_at,
            )
            updated = repository.get_candidate(job_id)
            if updated is None:
                raise RuntimeError("decided candidate could not be read back")
            result = _candidate_dict(updated)
            connection.execute("COMMIT")
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()
        return result

    def create_job(
        self,
        *,
        company_name: str,
        title: str,
        actor: str,
        city: str | None = None,
        detail_url: str | None = None,
        apply_url: str | None = None,
        careers_url: str | None = None,
        direction: str | None = None,
        recruitment_type: str | None = None,
        education_requirement: str | None = None,
        major_requirement: str | None = None,
        jd_text: str | None = None,
        published_at: str | None = None,
        deadline_at: str | None = None,
        lifecycle_status: str = "unknown",
        notes: str = "",
        company_type: str | None = None,
        company_city: str | None = None,
        next_follow_up_at: str | None = None,
        application_notes: str = "",
    ) -> dict[str, Any]:
        company_name = _require_nonempty_string("company_name", company_name)
        title = _require_nonempty_string("title", title)
        actor = _require_nonempty_string("actor", actor)
        direction = _normalize_job_text("direction", direction)
        city = _normalize_job_text("city", city)
        recruitment_type = _normalize_job_text("recruitment_type", recruitment_type)
        education_requirement = _normalize_job_text(
            "education_requirement", education_requirement
        )
        major_requirement = _normalize_job_text("major_requirement", major_requirement)
        jd_text = _normalize_job_text("jd_text", jd_text)
        detail_url = _normalize_url("detail_url", detail_url)
        apply_url = _normalize_url("apply_url", apply_url)
        careers_url = _normalize_url("careers_url", careers_url)
        published_at = _normalize_job_text("published_at", published_at)
        deadline_at = _normalize_job_text("deadline_at", deadline_at)
        lifecycle_status = _parse_lifecycle_status(lifecycle_status)
        notes = _normalize_notes("notes", notes)
        company_type = _normalize_job_text("company_type", company_type)
        company_city = _normalize_job_text("company_city", company_city)
        next_follow_up_at = _parse_next_follow_up_at(next_follow_up_at)
        application_notes = _normalize_notes("application_notes", application_notes)

        company_id = str(uuid4())
        job_id = str(uuid4())
        application_id = str(uuid4())
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            created_at = _utc_now()
            repository = BioJobRepository(connection)
            company = repository.upsert_company(
                company_id=company_id,
                canonical_name=company_name,
                company_type=company_type,
                city=company_city,
                aliases_json=_serialize_json("aliases", []),
                created_at=created_at,
                updated_at=created_at,
            )
            repository.insert_job(
                job_id=job_id,
                company_id=company["id"],
                title=title,
                direction=direction,
                city=city,
                recruitment_type=recruitment_type,
                education_requirement=education_requirement,
                major_requirement=major_requirement,
                jd_text=jd_text,
                detail_url=detail_url,
                apply_url=apply_url,
                careers_url=careers_url,
                published_at=published_at,
                deadline_at=deadline_at,
                lifecycle_status=lifecycle_status,
                notes=notes,
                created_at=created_at,
                updated_at=created_at,
            )
            initial_status = ApplicationStatus.CONSIDERING.value
            repository.insert_application(
                application_id=application_id,
                job_id=job_id,
                status=initial_status,
                applied_at=None,
                next_follow_up_at=next_follow_up_at,
                notes=application_notes,
                created_at=created_at,
                updated_at=created_at,
            )
            repository.insert_application_event(
                event_id=str(uuid4()),
                application_id=application_id,
                actor=actor,
                old_status=None,
                new_status=initial_status,
                note="",
                created_at=created_at,
            )
            self._insert_audit(
                repository,
                action="job.created",
                entity_id=job_id,
                entity_type="job",
                actor=actor,
                metadata={
                    "application_id": application_id,
                    "company_id": company["id"],
                    "status": initial_status,
                },
                created_at=created_at,
            )
            row = repository.get_job(job_id)
            if row is None:
                raise RuntimeError("created job could not be read back")
            result = _job_dict(row)
            connection.execute("COMMIT")
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()
        return result

    def transition_application(
        self,
        job_id: str,
        new_status: str | ApplicationStatus,
        *,
        actor: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        job_id = _require_nonempty_string("job_id", job_id)
        actor = _require_nonempty_string("actor", actor)
        new_status_value = _parse_application_status(new_status)
        note_value = "" if note is None else _normalize_notes("note", note)

        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            repository = BioJobRepository(connection)
            row = repository.get_job(job_id)
            if row is None:
                raise DomainNotFoundError(f"job not found: {job_id}")
            self._transition_application_in_transaction(
                repository,
                row=row,
                new_status=new_status_value,
                actor=actor,
                note=note_value,
            )
            updated = repository.get_job(job_id)
            if updated is None:
                raise RuntimeError("updated application could not be read back")
            result = _application_from_job_row(updated)
            connection.execute("COMMIT")
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()
        return result

    def _transition_application_in_transaction(
        self,
        repository: BioJobRepository,
        *,
        row: sqlite3.Row,
        new_status: str,
        actor: str,
        note: str,
        changed_at: str | None = None,
    ) -> None:
        _parse_persisted_lifecycle_status(row["lifecycle_status"], row["id"])
        current_status = _parse_persisted_application_status(
            row["application_status"], row["application_id"]
        )
        if new_status not in _APPLICATION_TRANSITIONS[current_status]:
            raise DomainConflictError(
                f"cannot transition application from {current_status!r} "
                f"to {new_status!r}"
            )
        changed_at = changed_at or _utc_now()
        applied_at = (
            changed_at if new_status == ApplicationStatus.APPLIED.value else None
        )
        repository.update_application_status(
            application_id=row["application_id"],
            status=new_status,
            applied_at=applied_at,
            updated_at=changed_at,
        )
        repository.insert_application_event(
            event_id=str(uuid4()),
            application_id=row["application_id"],
            actor=actor,
            old_status=current_status,
            new_status=new_status,
            note=note,
            created_at=changed_at,
        )
        self._insert_audit(
            repository,
            action="application.status_changed",
            entity_id=row["application_id"],
            entity_type="application",
            actor=actor,
            metadata={
                "job_id": row["id"],
                "old_status": current_status,
                "new_status": new_status,
                "note": note,
            },
            created_at=changed_at,
        )

    def get_job(self, job_id: str) -> dict[str, Any]:
        job_id = _require_nonempty_string("job_id", job_id)
        connection = self.database.connect()
        try:
            row = BioJobRepository(connection).get_job(job_id)
            if row is None:
                raise DomainNotFoundError(f"job not found: {job_id}")
            return _job_dict(row)
        finally:
            connection.close()

    def list_jobs(self) -> list[dict[str, Any]]:
        connection = self.database.connect()
        try:
            return [_job_dict(row) for row in BioJobRepository(connection).list_jobs()]
        finally:
            connection.close()

    def match_job(
        self,
        job_id: str,
        *,
        actor: str,
        model_provider: str | None = None,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        job_id = _require_nonempty_string("job_id", job_id)
        actor = _require_nonempty_string("actor", actor)
        model_provider = _normalize_optional_string("model_provider", model_provider)
        model_name = _normalize_optional_string("model_name", model_name)
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            repository = BioJobRepository(connection)
            job_row = repository.get_job(job_id)
            if job_row is None:
                raise DomainNotFoundError(f"job not found: {job_id}")
            facts = [
                _profile_fact_dict(row)
                for row in repository.list_usable_profile_facts(
                    status=ProfileFactStatus.CONFIRMED.value,
                    first_visibility=FactVisibility.MATCHING.value,
                    second_visibility=FactVisibility.BOTH.value,
                )
            ]
            report = build_match_report(_job_dict(job_row), facts)
            report["fact_ids"] = [fact["id"] for fact in facts]
            match_id = str(uuid4())
            created_at = _utc_now()
            repository.insert_job_match(
                match_id=match_id,
                job_id=job_id,
                score=report["score"],
                recommendation=report["recommendation"],
                evidence_json=_serialize_json("match report", report),
                model_provider=model_provider,
                model_name=model_name,
                rule_version=report["rule_version"],
                created_at=created_at,
            )
            self._insert_audit(
                repository,
                action="job.matched",
                entity_id=job_id,
                entity_type="job",
                actor=actor,
                metadata={
                    "match_id": match_id,
                    "score": report["score"],
                    "recommendation": report["recommendation"],
                    "rule_version": report["rule_version"],
                    "fact_ids": report["fact_ids"],
                },
                created_at=created_at,
            )
            row = repository.get_latest_job_match(job_id)
            if row is None:
                raise RuntimeError("created job match could not be read back")
            result = _match_dict(row)
            connection.execute("COMMIT")
            return result
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()

    def get_latest_match(self, job_id: str) -> dict[str, Any]:
        job_id = _require_nonempty_string("job_id", job_id)
        connection = self.database.connect()
        try:
            repository = BioJobRepository(connection)
            if repository.get_job(job_id) is None:
                raise DomainNotFoundError(f"job not found: {job_id}")
            row = repository.get_latest_job_match(job_id)
            if row is None:
                raise DomainNotFoundError(f"job match not found: {job_id}")
            return _match_dict(row)
        finally:
            connection.close()

    def update_job(
        self,
        job_id: str,
        *,
        actor: str,
        **changes: Any,
    ) -> dict[str, Any]:
        job_id = _require_nonempty_string("job_id", job_id)
        actor = _require_nonempty_string("actor", actor)
        if not changes:
            raise DomainValidationError("job update must include at least one field")
        unknown = (
            set(changes)
            - _JOB_UPDATE_FIELDS
            - {
                "application_status",
                "status",
                "next_follow_up_at",
                "application_notes",
            }
        )
        if unknown:
            raise DomainValidationError(
                f"unsupported job update field: {sorted(unknown)[0]}"
            )
        status_keys = {"application_status", "status"} & set(changes)
        if len(status_keys) > 1:
            raise DomainValidationError("provide only one application status field")
        status_value: str | None = None
        if status_keys:
            status_key = status_keys.pop()
            status_value = _parse_application_status(changes.pop(status_key))

        job_values: dict[str, str | None] = {}
        application_values: dict[str, str | None] = {}
        for field, value in changes.items():
            if field == "lifecycle_status":
                job_values[field] = _parse_lifecycle_status(value)
            elif field in _URL_FIELDS:
                job_values[field] = _normalize_url(field, value)
            elif field == "title":
                job_values[field] = _require_nonempty_string(field, value)
            elif field == "notes":
                job_values[field] = _normalize_notes(field, value)
            elif field == "next_follow_up_at":
                application_values[field] = _parse_next_follow_up_at(value)
            elif field == "application_notes":
                application_values["notes"] = _normalize_notes(field, value)
            else:
                job_values[field] = _normalize_job_text(field, value)

        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            repository = BioJobRepository(connection)
            current = repository.get_job(job_id)
            if current is None:
                raise DomainNotFoundError(f"job not found: {job_id}")
            _job_dict(current)
            updated_at = _utc_now()
            if job_values:
                repository.update_job_fields(
                    job_id=job_id,
                    values=job_values,
                    updated_at=updated_at,
                )
            if application_values:
                repository.update_application_fields(
                    application_id=current["application_id"],
                    values=application_values,
                    updated_at=updated_at,
                )
            if status_value is not None:
                self._transition_application_in_transaction(
                    repository,
                    row=current,
                    new_status=status_value,
                    actor=actor,
                    note="",
                    changed_at=updated_at,
                )
            if changes:
                self._insert_audit(
                    repository,
                    action="job.updated",
                    entity_id=job_id,
                    entity_type="job",
                    actor=actor,
                    metadata={"fields": sorted(changes)},
                    created_at=updated_at,
                )
            updated = repository.get_job(job_id)
            if updated is None:
                raise RuntimeError("updated job could not be read back")
            result = _job_dict(updated)
            connection.execute("COMMIT")
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()
        return result

    def soft_delete_job(self, job_id: str, *, actor: str) -> dict[str, Any]:
        job_id = _require_nonempty_string("job_id", job_id)
        actor = _require_nonempty_string("actor", actor)
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            repository = BioJobRepository(connection)
            current = repository.get_job(job_id)
            if current is None:
                raise DomainNotFoundError(f"job not found: {job_id}")
            deleted_at = _utc_now()
            repository.soft_delete_job(job_id=job_id, deleted_at=deleted_at)
            self._insert_audit(
                repository,
                action="job.deleted",
                entity_id=job_id,
                entity_type="job",
                actor=actor,
                metadata={"deleted_at": deleted_at},
                created_at=deleted_at,
            )
            result = _job_dict(current)
            result["deleted_at"] = deleted_at
            result["updated_at"] = deleted_at
            connection.execute("COMMIT")
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()
        return result

    def dashboard_counts(self) -> dict[str, int]:
        connection = self.database.connect()
        try:
            rows = BioJobRepository(connection).dashboard_counts()
            counts: dict[str, int] = {}
            for row in rows:
                status = _parse_persisted_application_status(
                    row["status"], row["sample_application_id"]
                )
                counts[status] = row["count"]
            return counts
        finally:
            connection.close()

    def list_application_events(self, job_id: str) -> list[dict[str, Any]]:
        job_id = _require_nonempty_string("job_id", job_id)
        connection = self.database.connect()
        try:
            history = BioJobRepository(connection).list_application_events(job_id)
            if history is None:
                raise DomainNotFoundError(f"job not found: {job_id}")
            application_id, rows = history
            events = [_application_event_dict(row, job_id=job_id) for row in rows]
            _validate_application_history(
                events,
                job_id=job_id,
                application_id=application_id,
            )
            return events
        finally:
            connection.close()

    def create_profile_fact(
        self,
        *,
        category: str,
        fact_key: str,
        value: Any,
        source_type: str,
        visibility: str | FactVisibility,
        actor: str,
        source_ref: str | None = None,
    ) -> dict[str, Any]:
        category = _require_nonempty_string("category", category)
        fact_key = _require_nonempty_string("fact_key", fact_key)
        source_type = _require_nonempty_string("source_type", source_type)
        actor = _require_nonempty_string("actor", actor)
        source_ref = _normalize_optional_string("source_ref", source_ref)
        visibility_value = _parse_visibility(visibility)
        value_json = _serialize_json("value", value)

        fact_id = str(uuid4())
        created_at = _utc_now()
        status = ProfileFactStatus.PENDING.value
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            repository = BioJobRepository(connection)
            repository.insert_profile_fact(
                fact_id=fact_id,
                category=category,
                fact_key=fact_key,
                value_json=value_json,
                source_type=source_type,
                source_ref=source_ref,
                status=status,
                visibility=visibility_value,
                confirmed_at=None,
                created_at=created_at,
                updated_at=created_at,
            )
            self._insert_audit(
                repository,
                action="profile_fact.created",
                entity_id=fact_id,
                actor=actor,
                metadata={
                    "category": category,
                    "fact_key": fact_key,
                    "status": status,
                    "visibility": visibility_value,
                },
                created_at=created_at,
            )
            row = repository.get_profile_fact(fact_id)
            connection.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            _rollback(connection)
            if _is_duplicate_profile_fact(exc):
                raise DomainConflictError(
                    f"profile fact already exists: ({category!r}, {fact_key!r})"
                ) from None
            raise
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()

        if row is None:
            raise RuntimeError("created profile fact could not be read back")
        return _profile_fact_dict(row)

    def set_profile_fact_status(
        self,
        fact_id: str,
        status: str | ProfileFactStatus,
        *,
        actor: str,
    ) -> dict[str, Any]:
        fact_id = _require_nonempty_string("fact_id", fact_id)
        actor = _require_nonempty_string("actor", actor)
        status_value = _parse_status(status)

        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            repository = BioJobRepository(connection)
            previous = repository.get_profile_fact(fact_id)
            if previous is None:
                raise DomainNotFoundError(f"profile fact not found: {fact_id}")
            _profile_fact_dict(previous)
            updated_at = _utc_now()
            confirmed_at = (
                updated_at
                if status_value == ProfileFactStatus.CONFIRMED.value
                else None
            )
            repository.update_profile_fact_status(
                fact_id=fact_id,
                status=status_value,
                confirmed_at=confirmed_at,
                updated_at=updated_at,
            )
            self._insert_audit(
                repository,
                action=f"profile_fact.{status_value}",
                entity_id=fact_id,
                actor=actor,
                metadata={
                    "old_status": previous["status"],
                    "new_status": status_value,
                },
                created_at=updated_at,
            )
            row = repository.get_profile_fact(fact_id)
            if row is None:
                raise RuntimeError("updated profile fact could not be read back")
            result = _profile_fact_dict(row)
            connection.execute("COMMIT")
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()

        return result

    def list_usable_facts(self, purpose: str) -> list[dict[str, Any]]:
        purpose = _require_nonempty_string("purpose", purpose)
        visibility_by_purpose = {
            "resume": FactVisibility.RESUME.value,
            "matching": FactVisibility.MATCHING.value,
        }
        if purpose not in visibility_by_purpose:
            raise DomainValidationError("purpose must be 'resume' or 'matching'")
        visibility = visibility_by_purpose[purpose]

        connection = self.database.connect()
        try:
            rows = BioJobRepository(connection).list_usable_profile_facts(
                status=ProfileFactStatus.CONFIRMED.value,
                first_visibility=visibility,
                second_visibility=FactVisibility.BOTH.value,
            )
            return [_profile_fact_dict(row) for row in rows]
        finally:
            connection.close()

    def list_profile_facts(self) -> list[dict[str, Any]]:
        connection = self.database.connect()
        try:
            rows = BioJobRepository(connection).list_profile_facts()
            return [_profile_fact_dict(row) for row in rows]
        finally:
            connection.close()

    def import_profile_document(
        self,
        file_path: str | Path,
        *,
        actor: str,
    ) -> dict[str, Any]:
        actor = _require_nonempty_string("actor", actor)
        source = Path(file_path).expanduser()
        if not source.is_file():
            raise DomainValidationError("profile document must be an existing file")
        document_type = source.suffix.casefold().lstrip(".")
        if document_type not in {"docx", "pdf"}:
            raise DomainValidationError("profile document must be a .docx or .pdf file")
        size = source.stat().st_size
        if size <= 0 or size > MAX_PROFILE_DOCUMENT_BYTES:
            raise DomainValidationError(
                "profile document must be between 1 byte and 10 MB"
            )
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        try:
            lines = extract_profile_lines(source)
        except (OSError, ValueError) as exc:
            raise DomainValidationError(
                f"profile document could not be read: {exc}"
            ) from exc
        if not lines:
            raise DomainValidationError("profile document contains no extractable text")

        destination = copy_profile_document(
            source,
            self.database.path.parent / "documents",
            digest,
        )
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            repository = BioJobRepository(connection)
            existing = repository.get_profile_document_by_sha256(digest)
            if existing is not None:
                result = dict(existing)
                result["fact_count"] = repository.count_profile_facts_by_source_ref(
                    existing["id"]
                )
                connection.execute("COMMIT")
                return result

            document_id = str(uuid4())
            created_at = _utc_now()
            repository.insert_profile_document(
                document_id=document_id,
                document_type=document_type,
                original_name=source.name,
                local_path=str(destination.resolve()),
                sha256=digest,
                created_at=created_at,
            )
            for index, line in enumerate(lines, start=1):
                repository.insert_profile_fact(
                    fact_id=str(uuid4()),
                    category="imported",
                    fact_key=f"document_{digest[:12]}_{index:02d}",
                    value_json=_serialize_json("value", line),
                    source_type="document",
                    source_ref=document_id,
                    status=ProfileFactStatus.PENDING.value,
                    visibility=FactVisibility.BOTH.value,
                    confirmed_at=None,
                    created_at=created_at,
                    updated_at=created_at,
                )
            self._insert_audit(
                repository,
                action="profile_document.imported",
                entity_type="profile_document",
                entity_id=document_id,
                actor=actor,
                metadata={
                    "document_type": document_type,
                    "original_name": source.name,
                    "sha256": digest,
                    "fact_count": len(lines),
                },
                created_at=created_at,
            )
            result = {
                "id": document_id,
                "document_type": document_type,
                "original_name": source.name,
                "local_path": str(destination.resolve()),
                "sha256": digest,
                "created_at": created_at,
                "fact_count": len(lines),
            }
            connection.execute("COMMIT")
            return result
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()

    def list_profile_documents(self) -> list[dict[str, Any]]:
        connection = self.database.connect()
        try:
            repository = BioJobRepository(connection)
            results = []
            for row in repository.list_profile_documents():
                item = dict(row)
                item["fact_count"] = repository.count_profile_facts_by_source_ref(
                    row["id"]
                )
                results.append(item)
            return results
        finally:
            connection.close()

    def generate_resume(self, job_id: str, *, actor: str) -> dict[str, Any]:
        job_id = _require_nonempty_string("job_id", job_id)
        actor = _require_nonempty_string("actor", actor)
        connection = self.database.connect()
        output: Path | None = None
        try:
            connection.execute("BEGIN IMMEDIATE")
            repository = BioJobRepository(connection)
            row = repository.get_job(job_id)
            if row is None:
                raise DomainNotFoundError(f"job not found: {job_id}")
            job = _job_dict(row)
            if job["application"]["status"] != ApplicationStatus.PREPARING.value:
                raise DomainConflictError(
                    "resume generation requires application status 'preparing'"
                )
            facts = [
                _profile_fact_dict(fact)
                for fact in repository.list_usable_profile_facts(
                    status=ProfileFactStatus.CONFIRMED.value,
                    first_visibility=FactVisibility.RESUME.value,
                    second_visibility=FactVisibility.BOTH.value,
                )
            ]
            if not facts:
                raise DomainConflictError(
                    "resume generation requires at least one confirmed resume fact"
                )
            resume_id = str(uuid4())
            created_at = _utc_now()
            company_name = _safe_export_component(job["company"]["name"], "company")
            title = _safe_export_component(job["title"], "job")
            output = (
                self.database.path.parent
                / "resumes"
                / f"{company_name}-{title}-{resume_id[:8]}.docx"
            )
            write_resume_docx(output, job=job, facts=facts)
            content_hash = hashlib.sha256(output.read_bytes()).hexdigest()
            facts_payload = [
                {
                    "id": fact["id"],
                    "category": fact["category"],
                    "fact_key": fact["fact_key"],
                    "value": fact["value"],
                }
                for fact in facts
            ]
            repository.insert_resume_version(
                resume_id=resume_id,
                job_id=job_id,
                file_path=str(output.resolve()),
                facts_json=_serialize_json("facts", facts_payload),
                template_name="biojob-ats-clean-v1",
                content_hash=content_hash,
                created_at=created_at,
            )
            self._insert_audit(
                repository,
                action="resume.generated",
                entity_type="resume_version",
                entity_id=resume_id,
                actor=actor,
                metadata={
                    "job_id": job_id,
                    "fact_ids": [fact["id"] for fact in facts],
                    "content_hash": content_hash,
                    "template_name": "biojob-ats-clean-v1",
                },
                created_at=created_at,
            )
            result = {
                "id": resume_id,
                "job_id": job_id,
                "file_path": str(output.resolve()),
                "facts": facts_payload,
                "fact_ids": [fact["id"] for fact in facts],
                "template_name": "biojob-ats-clean-v1",
                "content_hash": content_hash,
                "created_at": created_at,
            }
            connection.execute("COMMIT")
            return result
        except Exception:
            _rollback(connection)
            if output is not None and output.exists():
                output.unlink(missing_ok=True)
            raise
        finally:
            connection.close()

    def list_resume_versions(self, job_id: str | None = None) -> list[dict[str, Any]]:
        if job_id is not None:
            job_id = _require_nonempty_string("job_id", job_id)
        connection = self.database.connect()
        try:
            repository = BioJobRepository(connection)
            if job_id is not None and repository.get_job(job_id) is None:
                raise DomainNotFoundError(f"job not found: {job_id}")
            return [
                _resume_version_dict(row)
                for row in repository.list_resume_versions(job_id)
            ]
        finally:
            connection.close()

    def export_application_workbook(self, *, actor: str) -> dict[str, Any]:
        actor = _require_nonempty_string("actor", actor)
        connection = self.database.connect()
        try:
            repository = BioJobRepository(connection)
            jobs = [_job_dict(row) for row in repository.list_jobs()]
            matches = {
                row["job_id"]: _match_dict(row)
                for row in repository.list_latest_job_matches()
            }
            for job in jobs:
                job["latest_match"] = matches.get(job["id"])
            candidates = []
            for decision in CandidateDecision:
                candidates.extend(
                    _candidate_dict(row)
                    for row in repository.list_candidates(
                        decision=decision.value,
                        query=None,
                        direction=None,
                        city=None,
                    )
                )
            resumes = {
                row["job_id"]: row["file_path"]
                for row in repository.list_latest_resume_versions()
            }
        finally:
            connection.close()

        created_at = _utc_now()
        export_id = str(uuid4())
        export_dir = self.database.path.parent / "exports"
        report_dir = export_dir / "match-reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_paths: dict[str, str] = {}
        for job_id, report in matches.items():
            report_path = report_dir / f"{job_id}.json"
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
                encoding="utf-8",
            )
            report_paths[job_id] = str(report_path.resolve())
        output = export_dir / f"BioJob-投递表-{created_at[:10]}-{export_id[:8]}.xlsx"
        write_application_workbook(
            output,
            jobs=jobs,
            candidates=candidates,
            resume_by_job=resumes,
            match_report_by_job=report_paths,
        )
        with self.database.connect() as audit_connection:
            audit_connection.execute("BEGIN IMMEDIATE")
            repository = BioJobRepository(audit_connection)
            self._insert_audit(
                repository,
                action="applications.exported",
                entity_type="application_export",
                entity_id=export_id,
                actor=actor,
                metadata={
                    "job_count": len(jobs),
                    "candidate_count": len(candidates),
                    "sheet_names": list(WORKBOOK_SHEETS),
                },
                created_at=created_at,
            )
            audit_connection.execute("COMMIT")
        return {
            "id": export_id,
            "file_path": str(output.resolve()),
            "sheet_names": list(WORKBOOK_SHEETS),
            "job_count": len(jobs),
            "candidate_count": len(candidates),
            "created_at": created_at,
        }

    def list_audit_log(
        self,
        *,
        entity_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if entity_id is not None:
            entity_id = _require_nonempty_string("entity_id", entity_id)
        connection = self.database.connect()
        try:
            rows = BioJobRepository(connection).list_audit_log(entity_id)
            return [_audit_dict(row) for row in rows]
        finally:
            connection.close()

    @staticmethod
    def _insert_audit(
        repository: BioJobRepository,
        *,
        action: str,
        entity_id: str,
        actor: str,
        metadata: dict[str, Any],
        created_at: str,
        entity_type: str = "profile_fact",
    ) -> None:
        repository.insert_audit_log(
            audit_id=str(uuid4()),
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor=actor,
            metadata_json=_serialize_json("metadata", metadata),
            created_at=created_at,
        )


def _require_nonempty_string(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(f"{name} must be a non-empty string")
    return value.strip()


def _validate_source_config(
    adapter_type: str, config: Mapping[str, object]
) -> dict[str, str]:
    if not isinstance(config, Mapping):
        raise DomainValidationError("source config must be an object")
    if not all(isinstance(key, str) for key in config):
        raise DomainValidationError("source config keys must be strings")
    allowed_by_adapter = {
        "public_page": {"url", "company_name", "careers_url"},
        "feed": {"url", "company_name", "careers_url"},
        "manual": set(),
    }
    allowed = allowed_by_adapter.get(adapter_type, set())
    unknown = set(config) - allowed
    if unknown:
        raise DomainValidationError(
            f"unsupported source config field: {sorted(unknown)[0]}"
        )
    if adapter_type not in {"public_page", "feed", "manual"}:
        if config:
            raise DomainValidationError("custom source adapters require empty config")
        return {}
    if adapter_type == "manual":
        return {}
    url = _normalize_url("url", config.get("url"))
    if url is None:
        raise DomainValidationError("url must be a non-empty URL")
    result = {"url": url}
    company_name = _normalize_candidate_text("company_name", config.get("company_name"))
    if company_name is not None:
        result["company_name"] = company_name
    careers_url = _normalize_url("careers_url", config.get("careers_url"))
    if careers_url is not None:
        result["careers_url"] = careers_url
    return result


def _source_dict(row: sqlite3.Row) -> dict[str, Any]:
    result: dict[str, Any] = dict(row)
    source_id = result["id"]
    if not isinstance(source_id, str):
        raise DomainDataCorruptionError("corrupt source entity: id is invalid")
    config = _decode_json_field(
        result.pop("config_json"),
        table="sources",
        entity_id=source_id,
        field="config_json",
    )
    if not isinstance(config, dict) or not all(isinstance(key, str) for key in config):
        raise DomainDataCorruptionError(
            f"corrupt sources entity {source_id}: config_json must be an object"
        )
    adapter_type = result["adapter_type"]
    if not isinstance(adapter_type, str) or not adapter_type:
        raise DomainDataCorruptionError(
            f"corrupt source entity {source_id}: adapter_type is invalid"
        )
    try:
        config = _validate_source_config(adapter_type, config)
    except DomainValidationError as exc:
        raise DomainDataCorruptionError(
            f"corrupt sources entity {source_id}: config_json is invalid"
        ) from exc
    if result["enabled"] not in {0, 1}:
        raise DomainDataCorruptionError(
            f"corrupt source entity {source_id}: enabled is invalid"
        )
    if result["health_status"] not in {"unknown", "healthy", "degraded", "failed"}:
        raise DomainDataCorruptionError(
            f"corrupt source entity {source_id}: health_status is invalid"
        )
    result["enabled"] = bool(result["enabled"])
    result["config"] = config
    return result


def _source_run_dict(row: sqlite3.Row) -> dict[str, Any]:
    result: dict[str, Any] = dict(row)
    run_id = result["id"]
    if not isinstance(run_id, str):
        raise DomainDataCorruptionError("corrupt source run entity: id is invalid")
    if result["status"] not in {"running", "completed", "failed", "cancelled"}:
        raise DomainDataCorruptionError(
            f"corrupt source_runs entity {run_id}: status is invalid"
        )
    cursor = _decode_json_field(
        result.pop("cursor_json"),
        table="source_runs",
        entity_id=run_id,
        field="cursor_json",
    )
    if not isinstance(cursor, dict):
        raise DomainDataCorruptionError(
            f"corrupt source_runs entity {run_id}: cursor_json must be an object"
        )
    result_count = result["result_count"]
    if not isinstance(result_count, int) or result_count < 0:
        raise DomainDataCorruptionError(
            f"corrupt source_runs entity {run_id}: result_count is invalid"
        )
    result["cursor"] = cursor
    return result


def _normalize_optional_string(name: str, value: Any) -> str | None:
    if value is None:
        return None
    return _require_nonempty_string(name, value)


def _normalize_job_text(name: str, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DomainValidationError(f"{name} must be a string or null")
    value = value.strip()
    return value or None


def _normalize_candidate_text(
    name: str, value: Any, *, required: bool = False
) -> str | None:
    if value is None:
        if required:
            raise DomainValidationError(f"{name} must be a non-empty string")
        return None
    if not isinstance(value, str):
        suffix = "" if required else " or null"
        raise DomainValidationError(f"{name} must be a string{suffix}")
    normalized = re.sub(r"\s+", " ", value).strip()
    if not normalized:
        if required:
            raise DomainValidationError(f"{name} must be a non-empty string")
        return None
    return normalized


def _canonical_candidate_key(value: str | None) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.translate(
        str.maketrans({"，": ",", "。": ".", "：": ":", "；": ";"})
    )
    return re.sub(r"[\s,.;:，。；：·•/_-]+", "", normalized)


def _candidate_dedup_key(
    company_name: str,
    title: str,
    city: str | None,
    recruitment_type: str | None,
) -> str:
    identity = "\x1f".join(
        _canonical_candidate_key(value)
        for value in (company_name, title, city, recruitment_type)
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _infer_candidate_direction(title: str, jd_text: str | None) -> str | None:
    content = f"{title}\n{jd_text or ''}".upper()
    if any(term in content for term in ("QA", "QC", "质量", "GMP专员")):
        return "质量"
    if any(term in content for term in ("生产", "工艺", "发酵", "生物制药")):
        return "生产/工艺"
    if any(term in content for term in ("细胞培养", "实验员", "生物分析")):
        return "实验技术"
    return None


def _screen_candidate(*, title: str, jd_text: str | None) -> dict[str, Any]:
    content = f"{title}\n{jd_text or ''}"
    upper_content = content.upper()
    positive_terms = [term for term in _POSITIVE_TERMS if term.upper() in upper_content]
    hard_gaps = [term for term in _HARD_GAP_TERMS if term in content]
    score = max(
        0, min(100, 30 + min(60, len(positive_terms) * 9) - 25 * len(hard_gaps))
    )
    if hard_gaps:
        recommendation = "不建议"
    elif score >= 70:
        recommendation = "优先推荐"
    elif score >= 50:
        recommendation = "可以考虑"
    else:
        recommendation = "低匹配"
    return {
        "score": float(score),
        "recommendation": recommendation,
        "evidence": {
            "positive_terms": positive_terms,
            "hard_gaps": hard_gaps,
            "rule_version": _MATCH_RULE_VERSION,
        },
    }


def _normalize_notes(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise DomainValidationError(f"{name} must be a string")
    return value.strip()


def _normalize_url(name: str, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DomainValidationError(f"{name} must be a string or null")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise DomainValidationError(f"{name} must not contain control characters")
    value = value.strip()
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        parsed.port
    except ValueError as exc:
        raise DomainValidationError(
            f"{name} must be an absolute http or https URL with a valid host"
        ) from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or not _is_valid_url_hostname(hostname)
    ):
        raise DomainValidationError(
            f"{name} must be an absolute http or https URL with a valid host"
        )
    return value


def _is_valid_url_hostname(hostname: str) -> bool:
    if ":" in hostname:
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            return False
        return True
    if hostname.replace(".", "").isdigit():
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            return False
        return True
    try:
        ascii_hostname = hostname.rstrip(".").encode("idna").decode("ascii")
    except UnicodeError:
        return False
    if not ascii_hostname or len(ascii_hostname) > 253:
        return False
    return all(
        _DNS_LABEL_PATTERN.fullmatch(label) is not None
        for label in ascii_hostname.lower().split(".")
    )


def _parse_lifecycle_status(value: Any) -> str:
    if not isinstance(value, str):
        raise DomainValidationError("lifecycle_status must be a string")
    value = value.strip()
    if value not in {"open", "closed", "unknown"}:
        raise DomainValidationError("lifecycle_status must be open, closed, or unknown")
    return value


def _parse_next_follow_up_at(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DomainValidationError(
            "next_follow_up_at must be a timezone-aware ISO-8601 datetime or null"
        )
    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value)
        offset = parsed.utcoffset()
        if offset is None:
            raise ValueError("timezone is required")
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, TypeError, ValueError):
        raise DomainValidationError(
            "next_follow_up_at must be a timezone-aware ISO-8601 datetime or null"
        ) from None


def _parse_application_status(value: Any) -> str:
    try:
        if isinstance(value, str):
            value = value.strip()
        return ApplicationStatus(value).value
    except (TypeError, ValueError) as exc:
        raise DomainValidationError(
            "application status must be considering, preparing, applied, "
            "assessment, interview, offer, rejected, withdrawn, or expired"
        ) from exc


def _parse_candidate_decision(value: Any) -> str:
    try:
        if isinstance(value, str):
            value = value.strip()
        return CandidateDecision(value).value
    except (TypeError, ValueError) as exc:
        raise DomainValidationError(
            "candidate decision must be pending, kept, ignored, later, or error"
        ) from exc


def _parse_persisted_candidate_decision(value: Any, job_id: str) -> str:
    try:
        return CandidateDecision(value).value
    except (TypeError, ValueError):
        raise DomainDataCorruptionError(
            f"corrupt candidate entity {job_id}: decision is invalid"
        ) from None


def _parse_persisted_lifecycle_status(value: Any, job_id: str) -> str:
    if isinstance(value, str) and value in {"open", "closed", "unknown"}:
        return value
    raise DomainDataCorruptionError(
        f"corrupt job entity {job_id}: lifecycle_status is invalid"
    ) from None


def _parse_persisted_application_status(
    value: Any,
    entity_id: str,
    *,
    field: str = "status",
    entity_type: str = "application",
) -> str:
    try:
        return ApplicationStatus(value).value
    except (TypeError, ValueError):
        raise DomainDataCorruptionError(
            f"corrupt {entity_type} entity {entity_id}: {field} is invalid"
        ) from None


def _parse_visibility(value: Any) -> str:
    try:
        if isinstance(value, str):
            value = value.strip()
        return FactVisibility(value).value
    except (TypeError, ValueError) as exc:
        raise DomainValidationError(
            "visibility must be matching, resume, both, or private"
        ) from exc


def _parse_status(value: Any) -> str:
    try:
        if isinstance(value, str):
            value = value.strip()
        return ProfileFactStatus(value).value
    except (TypeError, ValueError) as exc:
        raise DomainValidationError(
            "status must be pending, confirmed, rejected, or conflicted"
        ) from exc


def _serialize_json(name: str, value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise DomainValidationError(f"{name} must be JSON serializable") from exc


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rollback(connection: sqlite3.Connection) -> None:
    if not connection.in_transaction:
        return
    try:
        connection.execute("ROLLBACK")
    except Exception:
        pass


def _is_duplicate_profile_fact(exc: sqlite3.IntegrityError) -> bool:
    message = str(exc).lower()
    return (
        "unique constraint failed" in message
        and "profile_facts.category" in message
        and "profile_facts.fact_key" in message
    )


def _profile_fact_dict(row: sqlite3.Row) -> dict[str, Any]:
    result: dict[str, Any] = dict(row)
    result["value"] = _decode_json_field(
        result.pop("value_json"),
        table="profile_facts",
        entity_id=result["id"],
        field="value_json",
    )
    return result


def _resume_version_dict(row: sqlite3.Row) -> dict[str, Any]:
    result: dict[str, Any] = dict(row)
    facts = _decode_json_field(
        result.pop("facts_json"),
        table="resume_versions",
        entity_id=result["id"],
        field="facts_json",
    )
    if not isinstance(facts, list) or any(
        not isinstance(fact, dict)
        or not isinstance(fact.get("id"), str)
        or not isinstance(fact.get("category"), str)
        or not isinstance(fact.get("fact_key"), str)
        for fact in facts
    ):
        raise DomainDataCorruptionError(
            f"corrupt resume_versions entity {result['id']}: facts_json has an invalid shape"
        )
    result["facts"] = facts
    result["fact_ids"] = [fact["id"] for fact in facts]
    return result


def _safe_export_component(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value).strip(" .-")
    return (cleaned or fallback)[:60]


def _match_dict(row: sqlite3.Row) -> dict[str, Any]:
    evidence = _decode_json_field(
        row["evidence_json"],
        table="job_matches",
        entity_id=row["id"],
        field="evidence_json",
    )
    if not isinstance(evidence, dict):
        raise DomainDataCorruptionError(
            f"corrupt job_matches entity {row['id']}: evidence_json has an invalid shape"
        )
    required = {
        "score": (int, float),
        "level": str,
        "recommendation": str,
        "blocked": bool,
        "hard_rules": list,
        "dimensions": list,
        "gaps": list,
        "risks": list,
        "confidence": str,
        "rule_version": str,
        "fact_ids": list,
    }
    if any(
        not isinstance(evidence.get(key), expected)
        for key, expected in required.items()
    ):
        raise DomainDataCorruptionError(
            f"corrupt job_matches entity {row['id']}: evidence_json has an invalid shape"
        )
    try:
        score = float(row["score"])
    except (TypeError, ValueError):
        score = math.nan
    if (
        not math.isfinite(score)
        or not 0 <= score <= 100
        or score != float(evidence["score"])
        or row["recommendation"] != evidence["recommendation"]
        or row["rule_version"] != evidence["rule_version"]
    ):
        raise DomainDataCorruptionError(
            f"corrupt job_matches entity {row['id']}: persisted metadata disagrees with evidence"
        )
    result = dict(evidence)
    result.update({
        "id": row["id"],
        "job_id": row["job_id"],
        "score": score,
        "recommendation": row["recommendation"],
        "model_provider": row["model_provider"],
        "model_name": row["model_name"],
        "rule_version": row["rule_version"],
        "created_at": row["created_at"],
    })
    return result


def _candidate_dict(row: sqlite3.Row) -> dict[str, Any]:
    result: dict[str, Any] = dict(row)
    job_id = result["id"]
    result["lifecycle_status"] = _parse_persisted_lifecycle_status(
        result["lifecycle_status"], job_id
    )
    decision = _parse_persisted_candidate_decision(result["candidate_decision"], job_id)
    evidence = _decode_json_field(
        result["match_evidence_json"],
        table="job_matches",
        entity_id=result["match_id"],
        field="evidence_json",
    )
    if (
        not isinstance(evidence, dict)
        or not isinstance(evidence.get("positive_terms"), list)
        or not isinstance(evidence.get("hard_gaps"), list)
    ):
        raise DomainDataCorruptionError(
            f"corrupt job_matches entity {result['match_id']}: "
            "evidence_json has an invalid shape"
        )
    try:
        score = float(result["match_score"])
    except (TypeError, ValueError):
        score = math.nan
    if not math.isfinite(score) or not 0 <= score <= 100:
        raise DomainDataCorruptionError(
            f"corrupt job_matches entity {result['match_id']}: score is invalid"
        )
    application = None
    if result["application_id"] is not None:
        application = {
            "id": result["application_id"],
            "job_id": job_id,
            "status": _parse_persisted_application_status(
                result["application_status"], result["application_id"]
            ),
            "applied_at": result["application_applied_at"],
            "next_follow_up_at": result["application_next_follow_up_at"],
            "notes": result["application_notes"],
            "created_at": result["application_created_at"],
            "updated_at": result["application_updated_at"],
        }
    company = {
        "id": result["company_id"],
        "canonical_name": result["company_name"],
        "name": result["company_name"],
        "company_type": result["company_company_type"],
        "city": result["company_city"],
    }
    links = {
        "detail": result["detail_url"],
        "apply": result["apply_url"],
        "careers": result["careers_url"],
    }
    match = {
        "id": result["match_id"],
        "score": score,
        "recommendation": result["match_recommendation"],
        "evidence": evidence,
        "model_provider": result["match_model_provider"],
        "model_name": result["match_model_name"],
        "rule_version": result["match_rule_version"],
        "created_at": result["match_created_at"],
    }
    decision_record = {
        "id": result["candidate_decision_id"],
        "decision": decision,
        "actor": result["candidate_decision_actor"],
        "note": result["candidate_decision_note"],
        "created_at": result["candidate_decision_created_at"],
    }
    for field in (
        "company_company_type",
        "company_city",
        "candidate_decision_id",
        "candidate_decision",
        "candidate_decision_actor",
        "candidate_decision_note",
        "candidate_decision_created_at",
        "match_id",
        "match_score",
        "match_recommendation",
        "match_evidence_json",
        "match_model_provider",
        "match_model_name",
        "match_rule_version",
        "match_created_at",
        "application_id",
        "application_status",
        "application_applied_at",
        "application_next_follow_up_at",
        "application_notes",
        "application_created_at",
        "application_updated_at",
    ):
        result.pop(field)
    result["decision"] = decision
    result["decision_record"] = decision_record
    result["match"] = match
    result["application"] = application
    result["company"] = company
    result["links"] = links
    return result


def _application_from_job_row(row: sqlite3.Row) -> dict[str, Any]:
    status = _parse_persisted_application_status(
        row["application_status"], row["application_id"]
    )
    return {
        "id": row["application_id"],
        "job_id": row["id"],
        "status": status,
        "applied_at": row["application_applied_at"],
        "next_follow_up_at": row["application_next_follow_up_at"],
        "notes": row["application_notes"],
        "created_at": row["application_created_at"],
        "updated_at": row["application_updated_at"],
    }


def _job_dict(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["lifecycle_status"] = _parse_persisted_lifecycle_status(
        row["lifecycle_status"], row["id"]
    )
    application = _application_from_job_row(row)
    company = {
        "id": row["company_id"],
        "canonical_name": row["company_name"],
        "name": row["company_name"],
        "company_type": row["company_company_type"],
        "city": row["company_city"],
    }
    links = {
        "detail": row["detail_url"],
        "apply": row["apply_url"],
        "careers": row["careers_url"],
    }
    for field in (
        "company_company_type",
        "company_city",
        "application_id",
        "application_status",
        "application_applied_at",
        "application_next_follow_up_at",
        "application_notes",
        "application_created_at",
        "application_updated_at",
    ):
        result.pop(field)
    result["company"] = company
    result["links"] = links
    result["application"] = application
    return result


def _application_event_dict(
    row: sqlite3.Row,
    *,
    job_id: str,
) -> dict[str, Any]:
    result: dict[str, Any] = dict(row)
    old_status = result["old_status"]
    if old_status is not None:
        try:
            result["old_status"] = _parse_persisted_application_status(
                old_status, result["id"]
            )
        except DomainDataCorruptionError:
            _raise_corrupt_application_history(
                job_id=job_id,
                application_id=result["application_id"],
                event_id=result["id"],
                detail="old_status is invalid",
            )
    try:
        result["new_status"] = _parse_persisted_application_status(
            result["new_status"], result["id"]
        )
    except DomainDataCorruptionError:
        _raise_corrupt_application_history(
            job_id=job_id,
            application_id=result["application_id"],
            event_id=result["id"],
            detail="new_status is invalid",
        )
    return result


def _validate_application_history(
    events: list[dict[str, Any]],
    *,
    job_id: str,
    application_id: str,
) -> None:
    if not events:
        _raise_corrupt_application_history(
            job_id=job_id,
            application_id=application_id,
            event_id="<missing>",
            detail="initial event is missing",
        )
    first = events[0]
    if (
        first["old_status"] is not None
        or first["new_status"] != ApplicationStatus.CONSIDERING.value
    ):
        _raise_corrupt_application_history(
            job_id=job_id,
            application_id=application_id,
            event_id=first["id"],
            detail="initial event must enter considering from no prior status",
        )
    previous_status = first["new_status"]
    for event in events[1:]:
        old_status = event["old_status"]
        new_status = event["new_status"]
        if old_status != previous_status:
            _raise_corrupt_application_history(
                job_id=job_id,
                application_id=application_id,
                event_id=event["id"],
                detail="old_status does not match the previous new_status",
            )
        if new_status not in _APPLICATION_TRANSITIONS[old_status]:
            _raise_corrupt_application_history(
                job_id=job_id,
                application_id=application_id,
                event_id=event["id"],
                detail=f"transition from {old_status!r} to {new_status!r} is invalid",
            )
        previous_status = new_status


def _raise_corrupt_application_history(
    *,
    job_id: str,
    application_id: str,
    event_id: str,
    detail: str,
) -> None:
    raise DomainDataCorruptionError(
        f"corrupt application history for job {job_id}, application "
        f"{application_id}, event {event_id}: {detail}"
    ) from None


def _audit_dict(row: sqlite3.Row) -> dict[str, Any]:
    result: dict[str, Any] = dict(row)
    result["metadata"] = _decode_json_field(
        result.pop("metadata_json"),
        table="audit_log",
        entity_id=result["id"],
        field="metadata_json",
    )
    return result


def _decode_json_field(
    raw_value: Any,
    *,
    table: str,
    entity_id: str,
    field: str,
) -> Any:
    try:
        return json.loads(
            raw_value,
            parse_constant=_reject_non_finite_json_constant,
            parse_float=_parse_finite_json_float,
        )
    except (UnicodeDecodeError, TypeError, ValueError):
        raise DomainDataCorruptionError(
            f"corrupt {table} entity {entity_id}: {field} is not valid strict JSON"
        ) from None


def _reject_non_finite_json_constant(constant: str) -> None:
    raise ValueError(f"non-finite JSON constant: {constant}")


def _parse_finite_json_float(number: str) -> float:
    value = float(number)
    if not math.isfinite(value):
        raise ValueError(f"non-finite JSON number: {number}")
    return value
