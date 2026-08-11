"""Transactional domain operations for the BioJob data core."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from biojob.database import BioJobDatabase
from biojob.domain import (
    DomainConflictError,
    DomainNotFoundError,
    DomainValidationError,
    FactVisibility,
    ProfileFactStatus,
)
from biojob.repository import BioJobRepository


class BioJobService:
    """Coordinate profile-fact validation, transactions, and audit records."""

    def __init__(self, database: BioJobDatabase | None = None) -> None:
        self.database = database or BioJobDatabase()
        self.database.initialize()

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
        if source_ref is not None and not isinstance(source_ref, str):
            raise DomainValidationError("source_ref must be a string or None")
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
        updated_at = _utc_now()
        confirmed_at = (
            updated_at if status_value == ProfileFactStatus.CONFIRMED.value else None
        )

        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            repository = BioJobRepository(connection)
            previous = repository.get_profile_fact(fact_id)
            if previous is None:
                raise DomainNotFoundError(f"profile fact not found: {fact_id}")
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
            connection.execute("COMMIT")
        except Exception:
            _rollback(connection)
            raise
        finally:
            connection.close()

        if row is None:
            raise RuntimeError("updated profile fact could not be read back")
        return _profile_fact_dict(row)

    def list_usable_facts(self, purpose: str) -> list[dict[str, Any]]:
        visibility_by_purpose = {
            "resume": FactVisibility.RESUME.value,
            "matching": FactVisibility.MATCHING.value,
        }
        if not isinstance(purpose, str) or purpose not in visibility_by_purpose:
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
    ) -> None:
        repository.insert_audit_log(
            audit_id=str(uuid4()),
            action=action,
            entity_type="profile_fact",
            entity_id=entity_id,
            actor=actor,
            metadata_json=_serialize_json("metadata", metadata),
            created_at=created_at,
        )


def _require_nonempty_string(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(f"{name} must be a non-empty string")
    return value


def _parse_visibility(value: Any) -> str:
    try:
        return FactVisibility(value).value
    except (TypeError, ValueError) as exc:
        raise DomainValidationError(
            "visibility must be matching, resume, both, or private"
        ) from exc


def _parse_status(value: Any) -> str:
    try:
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
    result["value"] = json.loads(result.pop("value_json"))
    return result


def _audit_dict(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["metadata"] = json.loads(result.pop("metadata_json"))
    return result
