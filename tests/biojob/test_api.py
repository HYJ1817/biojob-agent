from __future__ import annotations

import asyncio
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from biojob.domain import ApplicationStatus, DomainDataCorruptionError
from biojob.repository import BioJobRepository
from biojob.service import BioJobService
from hermes_cli.dashboard_auth.public_paths import PUBLIC_API_PATHS
from hermes_cli.web_routers import biojob as biojob_routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    app = FastAPI()
    app.include_router(biojob_routes.router)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _job_payload(**overrides):
    payload = {
        "company_name": " Acme Biotech ",
        "title": " Scientist ",
        "detail_url": "https://jobs.example.test/detail/1",
        "apply_url": "https://jobs.example.test/apply/1",
        "careers_url": "https://jobs.example.test/careers",
        "lifecycle_status": "open",
    }
    payload.update(overrides)
    return payload


def _create_job(client, **overrides):
    response = client.post("/api/biojob/jobs", json=_job_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def _create_fact(client, **overrides):
    payload = {
        "category": " laboratory ",
        "fact_key": " cck8 ",
        "value": {"skill": "CCK-8", "years": 2},
        "source_type": " user ",
        "visibility": "both",
    }
    payload.update(overrides)
    response = client.post("/api/biojob/profile-facts", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_job_round_trip_prepare_events_and_dashboard(client):
    created = _create_job(client)

    assert created["company"]["name"] == "Acme Biotech"
    assert created["title"] == "Scientist"
    assert created["detail_url"] == "https://jobs.example.test/detail/1"
    assert created["apply_url"] == "https://jobs.example.test/apply/1"
    assert created["careers_url"] == "https://jobs.example.test/careers"
    assert created["links"] == {
        "detail": created["detail_url"],
        "apply": created["apply_url"],
        "careers": created["careers_url"],
    }
    assert created["application"]["status"] == "considering"

    listed = client.get("/api/biojob/jobs")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [created["id"]]
    fetched = client.get(f"/api/biojob/jobs/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created

    prepared = client.post(f"/api/biojob/jobs/{created['id']}/prepare-application")
    assert prepared.status_code == 200
    assert prepared.json()["application"]["status"] == "preparing"

    events = client.get(f"/api/biojob/jobs/{created['id']}/events")
    assert events.status_code == 200
    assert [event["new_status"] for event in events.json()["items"]] == [
        "considering",
        "preparing",
    ]
    dashboard = client.get("/api/biojob/dashboard")
    assert dashboard.status_code == 200
    counts = dashboard.json()["application_counts"]
    assert set(counts) == {status.value for status in ApplicationStatus}
    assert counts["preparing"] == 1
    assert sum(counts.values()) == 1


def test_fact_create_list_confirm_and_purpose_filter(client):
    public = _create_fact(client)
    private = _create_fact(client, fact_key="private", visibility="private")

    assert public["status"] == "pending"
    assert public["category"] == "laboratory"
    assert public["fact_key"] == "cck8"
    assert public["value"] == {"skill": "CCK-8", "years": 2}
    assert "value_json" not in public
    all_facts = client.get("/api/biojob/profile-facts")
    assert all_facts.status_code == 200
    assert {fact["id"] for fact in all_facts.json()["items"]} == {
        public["id"],
        private["id"],
    }

    for fact in (public, private):
        response = client.patch(
            f"/api/biojob/profile-facts/{fact['id']}",
            json={"status": "confirmed"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "confirmed"

    usable = client.get("/api/biojob/profile-facts?purpose=resume")
    assert usable.status_code == 200
    assert [fact["id"] for fact in usable.json()["items"]] == [public["id"]]


def test_duplicate_fact_and_invalid_prepare_are_conflicts(client):
    _create_fact(client)
    duplicate = client.post(
        "/api/biojob/profile-facts",
        json={
            "category": "laboratory",
            "fact_key": "cck8",
            "value": "different",
            "source_type": "user",
            "visibility": "both",
        },
    )
    assert duplicate.status_code == 409

    job = _create_job(client)
    assert (
        client.post(f"/api/biojob/jobs/{job['id']}/prepare-application").status_code
        == 200
    )
    repeated = client.post(f"/api/biojob/jobs/{job['id']}/prepare-application")
    assert repeated.status_code == 409


def test_prepare_application_uses_atomic_job_update_boundary(client, monkeypatch):
    expected = {
        "id": "job-1",
        "application": {"status": "preparing"},
    }
    calls = []

    class RecordingService:
        def update_job(self, job_id, *, actor, **changes):
            calls.append((job_id, actor, changes))
            return expected

    monkeypatch.setattr(biojob_routes, "BioJobService", RecordingService)

    response = client.post("/api/biojob/jobs/job-1/prepare-application")

    assert response.status_code == 200, response.text
    assert response.json() == expected
    assert calls == [
        (
            "job-1",
            "biojob-api",
            {"application_status": ApplicationStatus.PREPARING},
        )
    ]


def test_prepare_readback_failure_rolls_back_entire_transaction(client, monkeypatch):
    job = _create_job(client)
    before_events = client.get(f"/api/biojob/jobs/{job['id']}/events").json()
    before_dashboard = client.get("/api/biojob/dashboard").json()
    before_audit = BioJobService().list_audit_log()
    real_get_job = BioJobRepository.get_job
    read_count = 0

    def fail_transaction_readback(repository, job_id):
        nonlocal read_count
        read_count += 1
        row = real_get_job(repository, job_id)
        if read_count == 2:
            return None
        return row

    with monkeypatch.context() as patch:
        patch.setattr(BioJobRepository, "get_job", fail_transaction_readback)
        response = client.post(f"/api/biojob/jobs/{job['id']}/prepare-application")

    assert response.status_code == 500
    assert response.json() == {"detail": "BioJob operation failed"}
    assert read_count == 2
    stored = client.get(f"/api/biojob/jobs/{job['id']}").json()
    assert stored["application"]["status"] == "considering"
    assert client.get(f"/api/biojob/jobs/{job['id']}/events").json() == before_events
    assert client.get("/api/biojob/dashboard").json() == before_dashboard
    assert BioJobService().list_audit_log() == before_audit


def test_patch_job_fields_and_legal_application_chain(client):
    job = _create_job(client)
    follow_up = "2030-02-03T04:05:06+08:00"
    patched = client.patch(
        f"/api/biojob/jobs/{job['id']}",
        json={
            "notes": " call recruiter ",
            "next_follow_up_at": follow_up,
            "lifecycle_status": "closed",
            "application_status": "preparing",
        },
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["notes"] == "call recruiter"
    assert body["lifecycle_status"] == "closed"
    assert body["application"]["next_follow_up_at"] == "2030-02-02T20:05:06Z"
    assert body["application"]["status"] == "preparing"

    applied = client.patch(
        f"/api/biojob/jobs/{job['id']}",
        json={"application_status": "applied"},
    )
    assert applied.status_code == 200
    assert applied.json()["application"]["applied_at"] is not None

    cleared = client.patch(
        f"/api/biojob/jobs/{job['id']}",
        json={"notes": None, "next_follow_up_at": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["notes"] == ""
    assert cleared.json()["application"]["next_follow_up_at"] is None

    whitespace_cleared = client.patch(
        f"/api/biojob/jobs/{job['id']}",
        json={"notes": "   "},
    )
    assert whitespace_cleared.status_code == 200
    assert whitespace_cleared.json()["notes"] == ""


def test_soft_delete_excludes_job_from_all_reads(client):
    job = _create_job(client)
    deleted = client.patch(f"/api/biojob/jobs/{job['id']}", json={"deleted": True})
    assert deleted.status_code == 200
    assert deleted.json()["deleted_at"] is not None
    assert client.get(f"/api/biojob/jobs/{job['id']}").status_code == 404
    assert client.get(f"/api/biojob/jobs/{job['id']}/events").status_code == 404
    assert client.get("/api/biojob/jobs").json() == {"items": []}
    assert (
        sum(client.get("/api/biojob/dashboard").json()["application_counts"].values())
        == 0
    )


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/biojob/jobs/missing", None),
        ("get", "/api/biojob/jobs/missing/events", None),
        ("post", "/api/biojob/jobs/missing/prepare-application", None),
        ("patch", "/api/biojob/profile-facts/missing", {"status": "confirmed"}),
    ],
)
def test_missing_entities_return_404(client, method, path, body):
    response = client.request(method, path, json=body)
    assert response.status_code == 404


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/api/biojob/jobs", _job_payload(company_name="   ")),
        ("post", "/api/biojob/jobs", _job_payload(extra="no")),
        ("post", "/api/biojob/jobs", _job_payload(detail_url="ftp://x.test/a")),
        ("post", "/api/biojob/jobs", _job_payload(apply_url="https://u:p@x.test/a")),
        ("post", "/api/biojob/jobs", _job_payload(notes="x" * 10_001)),
        ("post", "/api/biojob/jobs", _job_payload(jd_text="x" * 100_001)),
        (
            "post",
            "/api/biojob/profile-facts",
            {
                "category": " ",
                "fact_key": "x",
                "value": 1,
                "source_type": "user",
                "visibility": "both",
            },
        ),
        (
            "post",
            "/api/biojob/profile-facts",
            {
                "category": "x",
                "fact_key": "x",
                "value": 1,
                "source_type": "user",
                "visibility": "public",
            },
        ),
        ("patch", "/api/biojob/profile-facts/x", {}),
        ("patch", "/api/biojob/jobs/x", {}),
        ("patch", "/api/biojob/jobs/x", {"next_follow_up_at": "2030-01-01"}),
        ("patch", "/api/biojob/jobs/x", {"deleted": False}),
        ("patch", "/api/biojob/jobs/x", {"deleted": True, "notes": "x"}),
        ("patch", "/api/biojob/jobs/x", {"application_status": "pending"}),
    ],
)
def test_invalid_requests_return_422(client, method, path, body):
    response = client.request(method, path, json=body)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_profile_fact_rejects_non_finite_json_numbers(client, constant):
    response = client.post(
        "/api/biojob/profile-facts",
        content=(
            '{"category":"x","fact_key":"x","value":{"number":'
            f"{constant}"
            '},"source_type":"user","visibility":"both"}'
        ),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "method,path,content",
    [
        (
            "post",
            "/api/biojob/jobs",
            '{"company_name":NaN,"title":"Scientist"}',
        ),
        (
            "post",
            "/api/biojob/jobs",
            '{"company_name":"Acme","title":"Scientist","extra":{"nested":[Infinity]}}',
        ),
        ("patch", "/api/biojob/jobs/missing", '{"notes":-Infinity}'),
        (
            "patch",
            "/api/biojob/jobs/missing",
            '{"extra":{"nested":Infinity}}',
        ),
    ],
)
def test_all_request_models_reject_non_finite_json_without_writes(
    client, method, path, content
):
    response = client.request(
        method,
        path,
        content=content,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422, response.text
    assert client.get("/api/biojob/jobs").json() == {"items": []}


@pytest.mark.parametrize("deleted", ["true", 1, 1.0, False])
def test_deleted_accepts_only_json_true_and_never_coerces(client, deleted):
    job = _create_job(client)

    response = client.patch(
        f"/api/biojob/jobs/{job['id']}",
        json={"deleted": deleted},
    )

    assert response.status_code == 422, response.text
    assert client.get(f"/api/biojob/jobs/{job['id']}").status_code == 200


@pytest.mark.parametrize(
    "field",
    [
        "city",
        "direction",
        "recruitment_type",
        "education_requirement",
        "major_requirement",
        "published_at",
        "deadline_at",
        "company_type",
        "company_city",
        "jd_text",
        "detail_url",
        "notes",
        "application_notes",
    ],
)
def test_provided_optional_job_text_rejects_blank(client, field):
    response = client.post(
        "/api/biojob/jobs",
        json=_job_payload(**{field: "   "}),
    )

    assert response.status_code == 422, response.text
    assert client.get("/api/biojob/jobs").json() == {"items": []}


def test_provided_profile_fact_source_ref_rejects_blank(client):
    response = client.post(
        "/api/biojob/profile-facts",
        json={
            "category": "laboratory",
            "fact_key": "cck8",
            "value": {"skill": "CCK-8"},
            "source_type": "user",
            "source_ref": "   ",
            "visibility": "both",
        },
    )

    assert response.status_code == 422, response.text
    assert client.get("/api/biojob/profile-facts").json() == {"items": []}


def test_illegal_application_transition_returns_409(client):
    job = _create_job(client)
    response = client.patch(
        f"/api/biojob/jobs/{job['id']}",
        json={"application_status": "applied"},
    )
    assert response.status_code == 409


def test_handlers_offload_service_calls_to_threads(client, monkeypatch):
    calls = []
    real_to_thread = asyncio.to_thread

    async def recording_to_thread(func, /, *args, **kwargs):
        calls.append(func)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(biojob_routes.asyncio, "to_thread", recording_to_thread)

    response = client.get("/api/biojob/dashboard")

    assert response.status_code == 200
    assert calls


@pytest.mark.parametrize(
    "error",
    [
        sqlite3.DatabaseError("SELECT secret FROM /private/biojob.db"),
        DomainDataCorruptionError("corrupt /private/biojob.db at SELECT profile_facts"),
    ],
)
def test_internal_errors_are_sanitized(client, monkeypatch, error):
    class BrokenService:
        def __init__(self):
            raise error

    monkeypatch.setattr(biojob_routes, "BioJobService", BrokenService)

    response = client.get("/api/biojob/dashboard")

    assert response.status_code == 500
    assert response.json() == {"detail": "BioJob operation failed"}
    assert "/private" not in response.text
    assert "SELECT" not in response.text


def test_web_server_mount_respects_dashboard_auth_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from hermes_cli import web_server

    assert "/api/biojob/dashboard" not in PUBLIC_API_PATHS
    assert any(route.path == "/api/biojob/dashboard" for route in web_server.app.routes)
    previous = getattr(web_server.app.state, "auth_required", None)
    try:
        web_server.app.state.auth_required = True
        with TestClient(web_server.app) as gated:
            assert gated.get("/api/biojob/dashboard").status_code == 401
        web_server.app.state.auth_required = False
        with TestClient(web_server.app) as local:
            assert (
                local.get(
                    "/api/biojob/dashboard",
                    headers={
                        web_server._SESSION_HEADER_NAME: web_server._SESSION_TOKEN
                    },
                ).status_code
                == 200
            )
    finally:
        web_server.app.state.auth_required = previous
