"""Transactional domain operations for the BioJob data core."""

from __future__ import annotations

import ipaddress
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from biojob.database import BioJobDatabase
from biojob.domain import (
    ApplicationStatus,
    DomainConflictError,
    DomainDataCorruptionError,
    DomainNotFoundError,
    DomainValidationError,
    FactVisibility,
    ProfileFactStatus,
)
from biojob.repository import BioJobRepository


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


class BioJobService:
    """Coordinate profile-fact validation, transactions, and audit records."""

    def __init__(self, database: BioJobDatabase | None = None) -> None:
        self.database = database or BioJobDatabase()
        self.database.initialize()

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
                next_follow_up_at=None,
                notes="",
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
            current_status = _parse_persisted_application_status(
                row["application_status"], row["application_id"]
            )
            if new_status_value not in _APPLICATION_TRANSITIONS[current_status]:
                raise DomainConflictError(
                    f"cannot transition application from {current_status!r} "
                    f"to {new_status_value!r}"
                )
            changed_at = _utc_now()
            applied_at = (
                changed_at
                if new_status_value == ApplicationStatus.APPLIED.value
                else None
            )
            repository.update_application_status(
                application_id=row["application_id"],
                status=new_status_value,
                applied_at=applied_at,
                updated_at=changed_at,
            )
            repository.insert_application_event(
                event_id=str(uuid4()),
                application_id=row["application_id"],
                actor=actor,
                old_status=current_status,
                new_status=new_status_value,
                note=note_value,
                created_at=changed_at,
            )
            self._insert_audit(
                repository,
                action="application.status_changed",
                entity_id=row["application_id"],
                entity_type="application",
                actor=actor,
                metadata={
                    "job_id": job_id,
                    "old_status": current_status,
                    "new_status": new_status_value,
                    "note": note_value,
                },
                created_at=changed_at,
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
        if status_keys:
            if len(changes) != 1:
                raise DomainValidationError(
                    "application status changes must be submitted separately"
                )
            status_key = status_keys.pop()
            self.transition_application(
                job_id,
                changes[status_key],
                actor=actor,
            )
            return self.get_job(job_id)

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
                application_values[field] = _normalize_job_text(field, value)
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
            return {row["status"]: row["count"] for row in rows}
        finally:
            connection.close()

    def list_application_events(self, job_id: str) -> list[dict[str, Any]]:
        job_id = _require_nonempty_string("job_id", job_id)
        connection = self.database.connect()
        try:
            rows = BioJobRepository(connection).list_application_events(job_id)
            if rows is None:
                raise DomainNotFoundError(f"job not found: {job_id}")
            return [dict(row) for row in rows]
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


def _normalize_notes(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise DomainValidationError(f"{name} must be a string")
    return value.strip()


def _normalize_url(name: str, value: Any) -> str | None:
    value = _normalize_job_text(name, value)
    if value is None:
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
    if isinstance(value, str):
        value = value.strip()
    if value not in {"open", "closed", "unknown"}:
        raise DomainValidationError("lifecycle_status must be open, closed, or unknown")
    return value


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


def _parse_persisted_application_status(value: Any, application_id: str) -> str:
    try:
        return ApplicationStatus(value).value
    except (TypeError, ValueError):
        raise DomainDataCorruptionError(
            f"corrupt application entity {application_id}: invalid status"
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
    result = dict(row)
    result["value"] = _decode_json_field(
        result.pop("value_json"),
        table="profile_facts",
        entity_id=result["id"],
        field="value_json",
    )
    return result


def _application_from_job_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["application_id"],
        "job_id": row["id"],
        "status": row["application_status"],
        "applied_at": row["application_applied_at"],
        "next_follow_up_at": row["application_next_follow_up_at"],
        "notes": row["application_notes"],
        "created_at": row["application_created_at"],
        "updated_at": row["application_updated_at"],
    }


def _job_dict(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    application = _application_from_job_row(row)
    for field in (
        "application_id",
        "application_status",
        "application_applied_at",
        "application_next_follow_up_at",
        "application_notes",
        "application_created_at",
        "application_updated_at",
    ):
        result.pop(field)
    result["application"] = application
    return result


def _audit_dict(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
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
