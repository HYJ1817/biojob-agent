from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from biojob.service import BioJobService
from biojob.sources.catalog import DEFAULT_SOURCES
from hermes_cli.dashboard_auth.public_paths import PUBLIC_API_PATHS
from hermes_cli.web_routers import biojob as biojob_routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    app = FastAPI()
    app.include_router(biojob_routes.router)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def candidate_payload(**overrides):
    payload = {
        "company_name": "齐鲁制药",
        "title": "生物工艺工程师",
        "detail_url": "https://jobs.example.test/jobs/1",
        "apply_url": "https://jobs.example.test/apply/1",
        "careers_url": "https://jobs.example.test/careers",
        "city": "济南",
        "jd_text": "本科应届，负责发酵、生产和GMP记录。",
        "recruitment_type": "校招",
    }
    payload.update(overrides)
    return payload


def import_candidate(client, **overrides):
    response = client.post(
        "/api/biojob/candidates/import", json=candidate_payload(**overrides)
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_manual_import_lists_pending_candidate_and_retains_jump_links(client):
    candidate = import_candidate(client)

    assert candidate["decision"] == "pending"
    assert candidate["application"] is None
    assert candidate["links"] == {
        "detail": "https://jobs.example.test/jobs/1",
        "apply": "https://jobs.example.test/apply/1",
        "careers": "https://jobs.example.test/careers",
    }
    listed = client.get("/api/biojob/candidates")
    fetched = client.get(f"/api/biojob/candidates/{candidate['id']}")
    assert listed.status_code == 200
    assert listed.json()["items"] == [candidate]
    assert fetched.json() == candidate
    assert BioJobService().list_sources()[0]["name"] == "手工导入"


def test_duplicate_manual_import_merges_job_and_keeps_source_links(client):
    first = import_candidate(client)
    second = import_candidate(
        client,
        detail_url="https://mirror.example.test/jobs/1",
        apply_url="https://mirror.example.test/apply/1",
    )

    assert second["id"] == first["id"]
    assert second["source_count"] == 2
    assert len(client.get("/api/biojob/candidates").json()["items"]) == 1


def test_candidate_decisions_filters_and_keep_to_application(client):
    kept = import_candidate(client)
    later = import_candidate(
        client,
        title="QC实验员",
        city="烟台",
        detail_url="https://jobs.example.test/jobs/2",
        apply_url=None,
        jd_text="本科应届，负责QC质量检测。",
    )
    ignored = import_candidate(
        client,
        title="医药销售",
        city="青岛",
        detail_url="https://jobs.example.test/jobs/3",
        apply_url=None,
    )

    kept_response = client.post(
        f"/api/biojob/candidates/{kept['id']}/decision",
        json={"decision": "kept", "note": "准备投递"},
    )
    later_response = client.post(
        f"/api/biojob/candidates/{later['id']}/decision",
        json={"decision": "later"},
    )
    ignored_response = client.post(
        f"/api/biojob/candidates/{ignored['id']}/decision",
        json={"decision": "ignored", "note": "方向不符"},
    )

    assert kept_response.status_code == 200
    assert kept_response.json()["application"]["status"] == "considering"
    assert later_response.json()["decision"] == "later"
    assert ignored_response.json()["decision"] == "ignored"
    assert client.get("/api/biojob/candidates").json() == {"items": []}
    filtered = client.get(
        "/api/biojob/candidates",
        params={
            "decision": "later",
            "query": "QC",
            "direction": "质量",
            "city": "烟台",
        },
    )
    assert [item["id"] for item in filtered.json()["items"]] == [later["id"]]
    assert [job["id"] for job in client.get("/api/biojob/jobs").json()["items"]] == [
        kept["id"]
    ]


def test_candidate_missing_conflict_and_request_validation(client):
    assert client.get("/api/biojob/candidates/missing").status_code == 404
    assert (
        client.post(
            "/api/biojob/candidates/missing/decision",
            json={"decision": "kept"},
        ).status_code
        == 404
    )
    candidate = import_candidate(client)
    assert (
        client.post(
            f"/api/biojob/candidates/{candidate['id']}/decision",
            json={"decision": "kept"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/biojob/candidates/{candidate['id']}/decision",
            json={"decision": "kept"},
        ).status_code
        == 409
    )
    for payload in (
        candidate_payload(extra="forbidden"),
        candidate_payload(detail_url="file:///C:/job.txt"),
        candidate_payload(apply_url="https://user:pass@example.test/apply"),
        candidate_payload(jd_text="x" * 100_001),
    ):
        assert (
            client.post("/api/biojob/candidates/import", json=payload).status_code
            == 422
        )


def test_source_endpoints_seed_create_update_run_and_history(client):
    defaults = client.get("/api/biojob/sources")
    assert defaults.status_code == 200
    assert len(defaults.json()["items"]) == len(DEFAULT_SOURCES)

    created = client.post(
        "/api/biojob/sources",
        json={"name": "手工空来源", "adapter_type": "manual", "config": {}},
    )
    assert created.status_code == 201, created.text
    source = created.json()
    disabled = client.patch(
        f"/api/biojob/sources/{source['id']}", json={"enabled": False}
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert client.post(f"/api/biojob/sources/{source['id']}/run").status_code == 409
    assert client.post("/api/biojob/sources/missing/run").status_code == 404
    assert client.get("/api/biojob/source-runs").json() == {"items": []}


@pytest.mark.parametrize(
    "payload",
    [
        {
            "name": "未知适配器",
            "adapter_type": "shell",
            "config": {},
        },
        {
            "name": "密钥字段",
            "adapter_type": "public_page",
            "config": {"url": "https://jobs.example.test", "api_key": "secret"},
        },
        {
            "name": "本地路径",
            "adapter_type": "manual",
            "config": {"path": "C:/jobs.json"},
        },
    ],
)
def test_source_api_rejects_unknown_or_sensitive_config(client, payload):
    assert client.post("/api/biojob/sources", json=payload).status_code == 422


def test_source_run_failure_is_returned_and_isolated(client, monkeypatch):
    class FailingAdapter:
        adapter_type = "public_page"

        def fetch(self, config):
            raise RuntimeError("blocked by upstream")

    real_service = BioJobService(source_adapters={"public_page": FailingAdapter()})
    monkeypatch.setattr(biojob_routes, "BioJobService", lambda: real_service)
    source = real_service.create_source(
        name="失败官网",
        adapter_type="public_page",
        config={"url": "https://jobs.example.test"},
        actor="test",
    )

    response = client.post(f"/api/biojob/sources/{source['id']}/run")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    history = client.get("/api/biojob/source-runs", params={"source_id": source["id"]})
    assert history.json()["items"][0]["status"] == "failed"


def test_run_enabled_sources_endpoint_returns_isolated_batch_summary(
    client, monkeypatch
):
    class EmptyAdapter:
        adapter_type = "manual"

        def fetch(self, config):
            return []

    class FailingAdapter:
        adapter_type = "public_page"

        def fetch(self, config):
            raise RuntimeError("blocked by upstream")

    real_service = BioJobService(
        source_adapters={
            "manual": EmptyAdapter(),
            "public_page": FailingAdapter(),
        }
    )
    monkeypatch.setattr(biojob_routes, "BioJobService", lambda: real_service)
    real_service.create_source(
        name="可运行来源", adapter_type="manual", config={}, actor="test"
    )
    real_service.create_source(
        name="失败来源",
        adapter_type="public_page",
        config={"url": "https://jobs.example.test"},
        actor="test",
    )

    response = client.post("/api/biojob/sources/run-enabled")

    assert response.status_code == 200
    payload = response.json()
    assert {run["status"] for run in payload["runs"]} == {"completed", "failed"}
    assert payload["summary"] == {
        "completed_sources": 1,
        "failed_sources": 1,
        "new_candidates": 0,
        "merged_results": 0,
        "pending_verification": 0,
    }


def test_dashboard_includes_candidate_and_source_counts(client):
    pending = import_candidate(client)
    ignored = import_candidate(
        client,
        title="药物合成研究员",
        detail_url="https://jobs.example.test/jobs/2",
        apply_url=None,
    )
    client.post(
        f"/api/biojob/candidates/{ignored['id']}/decision",
        json={"decision": "ignored"},
    )
    client.get("/api/biojob/sources")

    dashboard = client.get("/api/biojob/dashboard").json()

    assert dashboard["candidate_counts"]["pending"] == 1
    assert dashboard["candidate_counts"]["ignored"] == 1
    assert dashboard["source_counts"]["total"] >= 6
    assert dashboard["source_counts"]["enabled"] >= 5
    assert pending["id"] != ignored["id"]


def test_discovery_routes_are_not_publicly_allowlisted():
    paths = {
        "/api/biojob/candidates",
        "/api/biojob/candidates/import",
        "/api/biojob/sources",
        "/api/biojob/source-runs",
    }
    assert paths.isdisjoint(PUBLIC_API_PATHS)


def test_real_web_server_auth_gate_rejects_discovery_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from hermes_cli import web_server

    paths = (
        "/api/biojob/candidates",
        "/api/biojob/sources",
        "/api/biojob/source-runs",
    )
    registered = {route.path for route in web_server.app.routes}
    assert set(paths) <= registered
    previous = getattr(web_server.app.state, "auth_required", None)
    try:
        web_server.app.state.auth_required = True
        with TestClient(web_server.app) as gated:
            assert all(gated.get(path).status_code == 401 for path in paths)
    finally:
        web_server.app.state.auth_required = previous
