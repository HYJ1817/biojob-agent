"""Isolated source-run orchestration for BioJob discovery."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from biojob.database import BioJobDatabase
from biojob.domain import DomainValidationError, RawJob
from biojob.repository import BioJobRepository
from biojob.sources.base import JobSourceAdapter
from biojob.sources.catalog import reviewed_hosts_for_source

if TYPE_CHECKING:
    from biojob.service import BioJobService


class DiscoveryRunner:
    """Run one adapter without holding a database lock during network I/O."""

    def __init__(
        self,
        database: BioJobDatabase,
        candidate_service: BioJobService,
        adapters: Mapping[str, JobSourceAdapter],
    ) -> None:
        self.database = database
        self.candidate_service = candidate_service
        self.adapters = adapters

    def run(self, source: dict[str, Any], *, actor: str) -> str:
        adapter = self.adapters[source["adapter_type"]]
        run_id = str(uuid4())
        started_at = _utc_now()
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            repository = BioJobRepository(connection)
            repository.insert_source_run(
                run_id=run_id,
                source_id=source["id"],
                started_at=started_at,
            )
            repository.insert_audit_log(
                audit_id=str(uuid4()),
                action="source.run_started",
                entity_type="source",
                entity_id=source["id"],
                actor=actor,
                metadata_json=json.dumps(
                    {"run_id": run_id}, ensure_ascii=False, separators=(",", ":")
                ),
                created_at=started_at,
            )
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

        try:
            runtime_config = dict(source["config"])
            reviewed_hosts = reviewed_hosts_for_source(source["id"])
            if reviewed_hosts:
                runtime_config["_reviewed_hosts"] = sorted(reviewed_hosts)
            items = adapter.fetch(runtime_config)
            if not isinstance(items, list):
                raise DomainValidationError("source adapter must return a list")
        except Exception as exc:
            self._finish(
                run_id=run_id,
                source_id=source["id"],
                status="failed",
                health_status="failed",
                result_count=0,
                error_summary=_safe_error(exc),
                actor=actor,
            )
            return run_id

        result_count = 0
        item_errors: list[str] = []
        for index, item in enumerate(items, start=1):
            try:
                if not isinstance(item, RawJob):
                    raise DomainValidationError("source item must be a RawJob")
                self.candidate_service.ingest_candidate(
                    item,
                    source_id=source["id"],
                    actor=f"source:{source['id']}",
                )
                result_count += 1
            except Exception as exc:
                item_errors.append(f"item {index}: {_safe_error(exc)}")
        error_summary = None
        health_status = "healthy"
        if item_errors:
            health_status = "degraded"
            details = "; ".join(item_errors)
            error_summary = f"{len(item_errors)} item(s) failed: {details}"[:500]
        self._finish(
            run_id=run_id,
            source_id=source["id"],
            status="completed",
            health_status=health_status,
            result_count=result_count,
            error_summary=error_summary,
            actor=actor,
        )
        return run_id

    def _finish(
        self,
        *,
        run_id: str,
        source_id: str,
        status: str,
        health_status: str,
        result_count: int,
        error_summary: str | None,
        actor: str,
    ) -> None:
        finished_at = _utc_now()
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            repository = BioJobRepository(connection)
            if (
                repository.finish_source_run(
                    run_id=run_id,
                    status=status,
                    result_count=result_count,
                    error_summary=error_summary,
                    finished_at=finished_at,
                )
                != 1
            ):
                raise RuntimeError("source run could not be finalized")
            repository.update_source_health(
                source_id=source_id,
                health_status=health_status,
                checked_at=finished_at,
            )
            repository.insert_audit_log(
                audit_id=str(uuid4()),
                action="source.run_finished",
                entity_type="source",
                entity_id=source_id,
                actor=actor,
                metadata_json=json.dumps(
                    {
                        "run_id": run_id,
                        "status": status,
                        "result_count": result_count,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                created_at=finished_at,
            )
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()


def _safe_error(error: Exception) -> str:
    message = re.sub(r"\s+", " ", str(error)).strip()
    message = re.sub(
        r"(?i)\b(api[_-]?key|authorization|cookie|token|password)\b\s*[:=]\s*\S+",
        r"\1=<redacted>",
        message,
    )
    message = re.sub(r"(?i)(https?://)[^/@\s]+@", r"\1<redacted>@", message)
    return (message or error.__class__.__name__)[:500]


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
