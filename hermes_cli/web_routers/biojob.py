"""FastAPI routes for the profile-scoped local BioJob data core."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Callable
from typing import Any, Literal, TypeVar

from fastapi import APIRouter, HTTPException, Query

from biojob.api_models import JobCreate, JobPatch, ProfileFactCreate, ProfileFactPatch
from biojob.domain import (
    ApplicationStatus,
    DomainConflictError,
    DomainDataCorruptionError,
    DomainNotFoundError,
    DomainValidationError,
)
from biojob.service import BioJobService


router = APIRouter(prefix="/api/biojob", tags=["biojob"])
_log = logging.getLogger(__name__)
_ACTOR = "biojob-api"
_Result = TypeVar("_Result")


async def _run_service(call: Callable[[], _Result]) -> _Result:
    try:
        return await asyncio.to_thread(call)
    except DomainNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DomainConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DomainValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (DomainDataCorruptionError, sqlite3.Error):
        _log.exception("BioJob data operation failed")
        raise HTTPException(status_code=500, detail="BioJob operation failed") from None
    except Exception:
        _log.exception("Unexpected BioJob operation failure")
        raise HTTPException(status_code=500, detail="BioJob operation failed") from None


@router.get("/dashboard")
async def dashboard() -> dict[str, dict[str, int]]:
    counts = await _run_service(lambda: BioJobService().dashboard_counts())
    application_counts = {status.value: 0 for status in ApplicationStatus}
    application_counts.update(counts)
    return {"application_counts": application_counts}


@router.get("/profile-facts")
async def list_profile_facts(
    purpose: Literal["resume", "matching"] | None = Query(default=None),
) -> dict[str, list[dict[str, Any]]]:
    def read() -> list[dict[str, Any]]:
        service = BioJobService()
        if purpose is not None:
            return service.list_usable_facts(purpose)
        return service.list_profile_facts()

    return {"items": await _run_service(read)}


@router.post("/profile-facts", status_code=201)
async def create_profile_fact(body: ProfileFactCreate) -> dict[str, Any]:
    values = body.model_dump()
    return await _run_service(
        lambda: BioJobService().create_profile_fact(actor=_ACTOR, **values)
    )


@router.patch("/profile-facts/{fact_id}")
async def patch_profile_fact(fact_id: str, body: ProfileFactPatch) -> dict[str, Any]:
    return await _run_service(
        lambda: BioJobService().set_profile_fact_status(
            fact_id, body.status, actor=_ACTOR
        )
    )


@router.get("/jobs")
async def list_jobs() -> dict[str, list[dict[str, Any]]]:
    return {"items": await _run_service(lambda: BioJobService().list_jobs())}


@router.post("/jobs", status_code=201)
async def create_job(body: JobCreate) -> dict[str, Any]:
    values = body.model_dump()
    return await _run_service(
        lambda: BioJobService().create_job(actor=_ACTOR, **values)
    )


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    return await _run_service(lambda: BioJobService().get_job(job_id))


@router.patch("/jobs/{job_id}")
async def patch_job(job_id: str, body: JobPatch) -> dict[str, Any]:
    values = body.model_dump(exclude_unset=True)
    if values.pop("deleted", None) is True:
        return await _run_service(
            lambda: BioJobService().soft_delete_job(job_id, actor=_ACTOR)
        )
    if "notes" in values and values["notes"] is None:
        values["notes"] = ""
    return await _run_service(
        lambda: BioJobService().update_job(job_id, actor=_ACTOR, **values)
    )


@router.post("/jobs/{job_id}/prepare-application")
async def prepare_application(job_id: str) -> dict[str, Any]:
    def prepare() -> dict[str, Any]:
        service = BioJobService()
        service.transition_application(
            job_id, ApplicationStatus.PREPARING, actor=_ACTOR
        )
        return service.get_job(job_id)

    return await _run_service(prepare)


@router.get("/jobs/{job_id}/events")
async def list_application_events(
    job_id: str,
) -> dict[str, list[dict[str, Any]]]:
    return {
        "items": await _run_service(
            lambda: BioJobService().list_application_events(job_id)
        )
    }
