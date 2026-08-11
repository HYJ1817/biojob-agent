from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import threading

import pytest

import biojob.service as service_module
from biojob.database import BioJobDatabase
from biojob.domain import (
    ApplicationStatus,
    DomainConflictError,
    DomainNotFoundError,
    DomainValidationError,
)
from biojob.repository import BioJobRepository
from biojob.service import BioJobService


@pytest.fixture
def database(tmp_path):
    database = BioJobDatabase(tmp_path / "biojob.db")
    database.initialize()
    return database


@pytest.fixture
def service(database):
    return BioJobService(database)


def create_job(service, **overrides):
    arguments = {
        "company_name": "荣昌生物",
        "title": "细胞培养技术员",
        "city": "烟台",
        "detail_url": "https://example.test/jobs/1",
        "apply_url": "https://example.test/apply/1",
        "careers_url": "https://example.test/careers",
        "actor": "user",
    }
    arguments.update(overrides)
    return service.create_job(**arguments)


def test_application_status_enum_has_the_persisted_values():
    assert {status.value for status in ApplicationStatus} == {
        "considering",
        "preparing",
        "applied",
        "assessment",
        "interview",
        "offer",
        "rejected",
        "withdrawn",
        "expired",
    }


def test_create_job_preserves_links_upserts_company_and_writes_initial_history(
    database,
    service,
):
    first = create_job(
        service,
        company_name="  荣昌生物  ",
        title="  细胞培养技术员  ",
        direction="细胞培养",
        recruitment_type="校招",
        education_requirement="本科",
        major_requirement="生物工程",
        jd_text="  第一行\n  第二行  ",
        published_at="2026-08-01",
        deadline_at="2026-09-01",
        lifecycle_status="open",
        notes="  重点岗位\n保留换行  ",
    )
    second = create_job(service, title="分析研究员")

    assert first["company_name"] == "荣昌生物"
    assert first["title"] == "细胞培养技术员"
    assert first["detail_url"] == "https://example.test/jobs/1"
    assert first["apply_url"] == "https://example.test/apply/1"
    assert first["careers_url"] == "https://example.test/careers"
    assert first["company"] == {
        "id": first["company_id"],
        "canonical_name": first["company_name"],
        "name": first["company_name"],
        "company_type": None,
        "city": None,
    }
    assert first["links"] == {
        "detail": "https://example.test/jobs/1",
        "apply": "https://example.test/apply/1",
        "careers": "https://example.test/careers",
    }
    assert first["jd_text"] == "第一行\n  第二行"
    assert first["notes"] == "重点岗位\n保留换行"
    assert first["application"]["status"] == "considering"
    assert first["application"]["applied_at"] is None
    assert first["application"]["job_id"] == first["id"]
    assert second["company_id"] == first["company_id"]

    events = service.list_application_events(first["id"])
    assert [(event["old_status"], event["new_status"]) for event in events] == [
        (None, "considering")
    ]
    assert events[0]["actor"] == "user"
    assert events[0]["note"] == ""
    audit = service.list_audit_log(entity_id=first["id"])
    assert [entry["action"] for entry in audit] == ["job.created"]
    assert audit[0]["entity_type"] == "job"

    with closing(database.connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 2
        )


def test_representative_forward_path_sets_applied_at_once(service):
    job = create_job(service)

    prepared = service.transition_application(job["id"], "preparing", actor="user")
    assert prepared["applied_at"] is None
    applied = service.transition_application(
        job["id"], "applied", actor="user", note=" 官网投递 "
    )
    first_applied_at = applied["applied_at"]
    assessed = service.transition_application(job["id"], "assessment", actor="system")
    interviewed = service.transition_application(job["id"], "interview", actor="user")
    offered = service.transition_application(job["id"], "offer", actor="user")

    assert first_applied_at is not None
    assert assessed["applied_at"] == first_applied_at
    assert interviewed["applied_at"] == first_applied_at
    assert offered["applied_at"] == first_applied_at
    events = service.list_application_events(job["id"])
    assert [event["new_status"] for event in events] == [
        "considering",
        "preparing",
        "applied",
        "assessment",
        "interview",
        "offer",
    ]
    assert events[2]["note"] == "官网投递"
    app_audit = service.list_audit_log(entity_id=job["application"]["id"])
    assert [entry["action"] for entry in app_audit] == [
        "application.status_changed"
    ] * 5
    assert app_audit[0]["metadata"] == {
        "job_id": job["id"],
        "old_status": "considering",
        "new_status": "preparing",
        "note": "",
    }


@pytest.mark.parametrize(
    "prefix,target",
    [
        ([], "withdrawn"),
        ([], "expired"),
        (["preparing"], "rejected"),
        (["preparing"], "withdrawn"),
        (["preparing"], "expired"),
        (["preparing", "applied"], "interview"),
        (["preparing", "applied"], "offer"),
        (["preparing", "applied"], "rejected"),
        (["preparing", "applied"], "expired"),
        (["preparing", "applied", "assessment"], "offer"),
        (["preparing", "applied", "assessment"], "rejected"),
        (["preparing", "applied", "assessment"], "expired"),
        (["preparing", "applied", "interview"], "rejected"),
        (["preparing", "applied", "interview"], "expired"),
    ],
)
def test_every_direct_forward_branch_is_allowed(service, prefix, target):
    job = create_job(service)
    for status in prefix:
        service.transition_application(job["id"], status, actor="user")

    result = service.transition_application(job["id"], target, actor="user")

    assert result["status"] == target


@pytest.mark.parametrize(
    "path,invalid_target",
    [
        (["preparing"], "preparing"),
        (["preparing", "applied"], "considering"),
        (["withdrawn"], "preparing"),
        (["expired"], "rejected"),
        (["preparing", "rejected"], "offer"),
        (["preparing", "applied", "offer"], "withdrawn"),
    ],
)
def test_invalid_transition_is_conflict_without_side_effects(
    service,
    path,
    invalid_target,
):
    job = create_job(service)
    for status in path:
        service.transition_application(job["id"], status, actor="user")
    application_id = job["application"]["id"]
    before = service.get_job(job["id"])["application"]
    events_before = service.list_application_events(job["id"])
    audit_before = service.list_audit_log(entity_id=application_id)

    with pytest.raises(DomainConflictError):
        service.transition_application(job["id"], invalid_target, actor="user")

    assert service.get_job(job["id"])["application"] == before
    assert service.list_application_events(job["id"]) == events_before
    assert service.list_audit_log(entity_id=application_id) == audit_before


@pytest.mark.parametrize("status", ["", "pending", None, 3])
def test_transition_rejects_unknown_application_status(service, status):
    job = create_job(service)

    with pytest.raises(DomainValidationError):
        service.transition_application(job["id"], status, actor="user")


@pytest.mark.parametrize(
    "field,value",
    [
        ("company_name", "  "),
        ("title", ""),
        ("actor", None),
    ],
)
def test_create_job_rejects_blank_required_fields(service, field, value):
    with pytest.raises(DomainValidationError):
        create_job(service, **{field: value})


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///tmp/job",
        "/jobs/1",
        "https:///jobs/1",
        "https://",
        "ftp://example.test/jobs/1",
        "https://-example.test/jobs/1",
        "https://example..test/jobs/1",
        "https://exa_mple.test/jobs/1",
    ],
)
def test_create_job_rejects_unsafe_or_hostless_urls(service, url):
    with pytest.raises(DomainValidationError):
        create_job(service, detail_url=url)


def test_blank_optional_url_is_stored_as_none(service):
    job = create_job(service, detail_url="  ", apply_url=None, careers_url="")

    assert job["detail_url"] is None
    assert job["apply_url"] is None
    assert job["careers_url"] is None
    assert job["links"] == {"detail": None, "apply": None, "careers": None}


@pytest.mark.parametrize("status", ["opening", "", None, 3])
def test_create_job_rejects_invalid_lifecycle_status(service, status):
    with pytest.raises(DomainValidationError):
        create_job(service, lifecycle_status=status)


def test_create_job_rolls_back_company_job_application_event_and_audit_on_failure(
    database,
    monkeypatch,
):
    def fail_event(*args, **kwargs):
        raise RuntimeError("synthetic event failure")

    monkeypatch.setattr(BioJobRepository, "insert_application_event", fail_event)
    service = BioJobService(database)

    with pytest.raises(RuntimeError, match="synthetic event failure"):
        create_job(service)

    with closing(database.connect()) as connection:
        for table in (
            "companies",
            "jobs",
            "applications",
            "application_events",
            "audit_log",
        ):
            assert (
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            )


def test_list_and_get_jobs_are_stable_and_embed_application(
    service,
    monkeypatch,
):
    monkeypatch.setattr(service_module, "_utc_now", lambda: "2099-01-01T00:00:00+00:00")
    first = create_job(service, title="first")
    second = create_job(service, title="second")

    listed = service.list_jobs()

    assert [job["id"] for job in listed] == [second["id"], first["id"]]
    assert service.get_job(first["id"]) == first
    assert all(job["application"]["status"] == "considering" for job in listed)
    assert listed[0]["company"] == {
        "id": listed[0]["company_id"],
        "canonical_name": listed[0]["company_name"],
        "name": listed[0]["company_name"],
        "company_type": None,
        "city": None,
    }
    assert listed[0]["links"] == {
        "detail": "https://example.test/jobs/1",
        "apply": "https://example.test/apply/1",
        "careers": "https://example.test/careers",
    }
    assert listed[0]["detail_url"] == "https://example.test/jobs/1"
    assert listed[0]["apply_url"] == "https://example.test/apply/1"
    assert listed[0]["careers_url"] == "https://example.test/careers"


def test_application_events_preserve_insert_causality_for_equal_timestamps(
    service,
    monkeypatch,
):
    monkeypatch.setattr(service_module, "_utc_now", lambda: "2099-01-01T00:00:00+00:00")
    job = create_job(service)
    service.transition_application(job["id"], "preparing", actor="user")
    service.transition_application(job["id"], "applied", actor="user")

    events = service.list_application_events(job["id"])

    assert [event["new_status"] for event in events] == [
        "considering",
        "preparing",
        "applied",
    ]


def test_update_job_uses_whitelist_updates_application_fields_and_audits(service):
    job = create_job(service)

    updated = service.update_job(
        job["id"],
        actor=" editor ",
        notes="  联系人：张老师\n周五跟进  ",
        next_follow_up_at=" 2026-08-14T09:00:00+08:00 ",
        lifecycle_status=" closed ",
        city=" 上海 ",
    )

    assert updated["notes"] == "联系人：张老师\n周五跟进"
    assert updated["city"] == "上海"
    assert updated["lifecycle_status"] == "closed"
    assert updated["application"]["next_follow_up_at"] == ("2026-08-14T09:00:00+08:00")
    assert updated["company"]["canonical_name"] == updated["company_name"]
    assert updated["links"] == {
        "detail": "https://example.test/jobs/1",
        "apply": "https://example.test/apply/1",
        "careers": "https://example.test/careers",
    }
    audit = service.list_audit_log(entity_id=job["id"])
    assert audit[-1]["action"] == "job.updated"
    assert audit[-1]["actor"] == "editor"
    assert set(audit[-1]["metadata"]["fields"]) == {
        "city",
        "lifecycle_status",
        "next_follow_up_at",
        "notes",
    }


def test_update_job_rejects_empty_or_unknown_patch(service):
    job = create_job(service)

    with pytest.raises(DomainValidationError):
        service.update_job(job["id"], actor="user")
    with pytest.raises(DomainValidationError):
        service.update_job(job["id"], actor="user", deleted_at="now")


def test_update_job_routes_application_status_through_transition_rules(service):
    job = create_job(service)

    with pytest.raises(DomainConflictError):
        service.update_job(job["id"], actor="user", status="applied")
    prepared = service.update_job(
        job["id"], actor="user", application_status="preparing"
    )

    assert prepared["application"]["status"] == "preparing"
    assert [
        event["new_status"] for event in service.list_application_events(job["id"])
    ] == ["considering", "preparing"]


def test_soft_delete_hides_job_and_history_from_public_operations(service):
    kept = create_job(service, title="kept")
    deleted = create_job(service, title="deleted")
    service.transition_application(deleted["id"], "withdrawn", actor="user")

    removed = service.soft_delete_job(deleted["id"], actor="user")

    assert removed["deleted_at"] is not None
    assert [job["id"] for job in service.list_jobs()] == [kept["id"]]
    for operation in (
        lambda: service.get_job(deleted["id"]),
        lambda: service.transition_application(
            deleted["id"], "preparing", actor="user"
        ),
        lambda: service.list_application_events(deleted["id"]),
    ):
        with pytest.raises(DomainNotFoundError):
            operation()
    assert service.list_audit_log(entity_id=deleted["id"])[-1]["action"] == (
        "job.deleted"
    )


def test_dashboard_counts_group_application_status_and_exclude_deleted(service):
    considering = create_job(service, title="considering")
    preparing = create_job(service, title="preparing")
    deleted = create_job(service, title="deleted")
    service.transition_application(preparing["id"], "preparing", actor="user")
    service.soft_delete_job(deleted["id"], actor="user")

    counts = service.dashboard_counts()

    assert counts == {"considering": 1, "preparing": 1}
    assert considering["id"] != preparing["id"]


def test_concurrent_same_transition_has_one_success_and_unbroken_event_chain(
    database,
):
    service = BioJobService(database)
    job = create_job(service)
    start = threading.Barrier(2)

    def prepare():
        start.wait()
        try:
            return service.transition_application(
                job["id"], "preparing", actor="worker"
            )["status"]
        except DomainConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: prepare(), range(2)))

    assert sorted(results) == ["conflict", "preparing"]
    events = service.list_application_events(job["id"])
    assert [(event["old_status"], event["new_status"]) for event in events] == [
        (None, "considering"),
        ("considering", "preparing"),
    ]


def test_missing_or_deleted_job_operations_raise_not_found(service):
    with pytest.raises(DomainNotFoundError):
        service.get_job("missing")
    with pytest.raises(DomainNotFoundError):
        service.list_application_events("missing")
    with pytest.raises(DomainNotFoundError):
        service.transition_application("missing", "preparing", actor="user")
    with pytest.raises(DomainNotFoundError):
        service.update_job("missing", actor="user", notes="x")
    with pytest.raises(DomainNotFoundError):
        service.soft_delete_job("missing", actor="user")
