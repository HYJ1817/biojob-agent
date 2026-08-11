from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_cli.web_routers import biojob as biojob_routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    app = FastAPI()
    app.include_router(biojob_routes.router)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _create_preparing_job(client: TestClient) -> dict:
    job = client.post(
        "/api/biojob/jobs",
        json={"company_name": "荣昌生物", "title": "细胞培养技术员"},
    ).json()
    response = client.post(f"/api/biojob/jobs/{job['id']}/prepare-application")
    assert response.status_code == 200
    return job


def _confirmed_fact(client: TestClient) -> dict:
    fact = client.post(
        "/api/biojob/profile-facts",
        json={
            "category": "skills",
            "fact_key": "cell_culture",
            "value": "完成NK细胞复苏、计数与CCK-8检测",
            "source_type": "user",
            "visibility": "both",
        },
    ).json()
    return client.patch(
        f"/api/biojob/profile-facts/{fact['id']}", json={"status": "confirmed"}
    ).json()


def test_document_resume_and_export_routes(client: TestClient, tmp_path: Path):
    source = tmp_path / "base.docx"
    document = Document()
    document.add_paragraph("细胞培养和CCK-8检测")
    document.save(source)

    imported = client.post(
        "/api/biojob/profile-documents/import", json={"file_path": str(source)}
    )
    assert imported.status_code == 201, imported.text
    assert (
        client.get("/api/biojob/profile-documents").json()["items"][0]["id"]
        == imported.json()["id"]
    )

    job = _create_preparing_job(client)
    _confirmed_fact(client)
    generated = client.post(f"/api/biojob/jobs/{job['id']}/resumes")
    assert generated.status_code == 201, generated.text
    assert Path(generated.json()["file_path"]).is_file()
    listed = client.get(f"/api/biojob/jobs/{job['id']}/resumes")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == generated.json()["id"]

    exported = client.post("/api/biojob/exports/applications")
    assert exported.status_code == 201, exported.text
    assert Path(exported.json()["file_path"]).is_file()


def test_document_import_validates_body_and_missing_file(client: TestClient):
    assert (
        client.post("/api/biojob/profile-documents/import", json={}).status_code == 422
    )
    assert (
        client.post(
            "/api/biojob/profile-documents/import",
            json={"file_path": "missing.docx", "unknown": True},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/biojob/profile-documents/import",
            json={"file_path": "missing.docx"},
        ).status_code
        == 422
    )
