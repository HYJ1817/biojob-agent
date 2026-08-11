from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from biojob.database import BioJobDatabase
from biojob.domain import DomainDataCorruptionError
from biojob.service import BioJobService
from hermes_cli.web_routers import biojob as biojob_routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    app = FastAPI()
    app.include_router(biojob_routes.router)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _create_job(client: TestClient):
    response = client.post(
        "/api/biojob/jobs",
        json={
            "company_name": "齐鲁制药",
            "title": "生物工艺工程师",
            "city": "济南",
            "direction": "生物工艺",
            "recruitment_type": "2027届校园招聘",
            "education_requirement": "本科及以上",
            "major_requirement": "生物工程相关专业",
            "jd_text": "负责细胞培养、发酵工艺、GMP生产记录，应届生可投。",
            "detail_url": "https://jobs.example.test/1",
            "lifecycle_status": "open",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _confirmed_fact(client: TestClient, key: str, value, *, visibility="both"):
    created = client.post(
        "/api/biojob/profile-facts",
        json={
            "category": "skills"
            if key
            not in {"degree", "major", "graduation_year", "target_directions", "cities"}
            else "education",
            "fact_key": key,
            "value": value,
            "source_type": "user",
            "visibility": visibility,
        },
    ).json()
    return client.patch(
        f"/api/biojob/profile-facts/{created['id']}", json={"status": "confirmed"}
    ).json()


def test_match_endpoint_uses_only_confirmed_matching_facts_and_returns_latest(client):
    job = _create_job(client)
    used = _confirmed_fact(client, "cell_culture", "细胞培养")
    _confirmed_fact(client, "fermentation", "发酵工程")
    private = _confirmed_fact(client, "invented", "诺贝尔奖", visibility="private")
    client.post(
        "/api/biojob/profile-facts",
        json={
            "category": "skills",
            "fact_key": "pending-paper",
            "value": "顶级论文",
            "source_type": "user",
            "visibility": "both",
        },
    )

    first = client.post(
        f"/api/biojob/jobs/{job['id']}/match",
        json={"model_provider": "deterministic", "model_name": "rules-v2"},
    )
    second = client.post(f"/api/biojob/jobs/{job['id']}/match", json={})
    fetched = client.get(f"/api/biojob/jobs/{job['id']}/match")

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert fetched.status_code == 200
    assert fetched.json()["id"] == second.json()["id"]
    assert first.json()["model_provider"] == "deterministic"
    assert first.json()["model_name"] == "rules-v2"
    assert len(first.json()["fact_ids"]) == 2
    assert used["id"] in first.json()["fact_ids"]
    serialized = json.dumps(first.json(), ensure_ascii=False)
    assert "诺贝尔奖" not in serialized
    assert "顶级论文" not in serialized
    assert private["id"] not in first.json()["fact_ids"]


def test_match_missing_job_or_report_and_strict_body_validation(client):
    job = _create_job(client)

    assert client.get(f"/api/biojob/jobs/{job['id']}/match").status_code == 404
    assert client.post("/api/biojob/jobs/missing/match", json={}).status_code == 404
    assert client.get("/api/biojob/jobs/missing/match").status_code == 404
    assert (
        client.post(
            f"/api/biojob/jobs/{job['id']}/match", json={"unknown": "value"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/biojob/jobs/{job['id']}/match",
            json={"model_provider": "   "},
        ).status_code
        == 422
    )


def test_corrupt_persisted_match_fails_closed(tmp_path):
    database = BioJobDatabase(tmp_path / "biojob.db")
    service = BioJobService(database)
    job = service.create_job(
        company_name="示例生物",
        title="QC实验员",
        actor="test",
    )
    report = service.match_job(job["id"], actor="test")
    with database.connect() as connection:
        connection.execute(
            "UPDATE job_matches SET evidence_json = ? WHERE id = ?",
            ('{"score": NaN}', report["id"]),
        )

    with pytest.raises(DomainDataCorruptionError):
        service.get_latest_match(job["id"])


def test_match_audit_contains_metadata_but_not_fact_or_jd_contents(tmp_path):
    service = BioJobService(BioJobDatabase(tmp_path / "biojob.db"))
    job = service.create_job(
        company_name="示例生物",
        title="发酵工程师",
        jd_text="机密JD原文",
        actor="test",
    )
    fact = service.create_profile_fact(
        category="skills",
        fact_key="secret-skill",
        value="机密个人事实",
        source_type="user",
        visibility="both",
        actor="test",
    )
    service.set_profile_fact_status(fact["id"], "confirmed", actor="test")

    service.match_job(job["id"], actor="test")
    audit = service.list_audit_log(entity_id=job["id"])[-1]
    serialized = json.dumps(audit, ensure_ascii=False)

    assert audit["action"] == "job.matched"
    assert "机密JD原文" not in serialized
    assert "机密个人事实" not in serialized
