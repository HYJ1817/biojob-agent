from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from biojob.database import BioJobDatabase
from biojob.domain import DomainConflictError, DomainValidationError
from biojob.service import BioJobService


def _service(tmp_path: Path) -> BioJobService:
    return BioJobService(BioJobDatabase(tmp_path / "biojob.db"))


def _job(service: BioJobService, *, status: str = "considering") -> dict:
    job = service.create_job(
        company_name="齐鲁制药",
        title="生物工艺工程师",
        city="济南",
        jd_text="负责细胞培养、发酵工艺与GMP生产记录，应届本科生可投。",
        detail_url="https://jobs.example.test/detail/1",
        apply_url="https://jobs.example.test/apply/1",
        careers_url="https://jobs.example.test/careers",
        actor="test",
    )
    if status == "preparing":
        service.transition_application(job["id"], "preparing", actor="test")
    return service.get_job(job["id"])


def _fact(
    service: BioJobService,
    key: str,
    value: object,
    *,
    status: str = "confirmed",
    visibility: str = "both",
) -> dict:
    fact = service.create_profile_fact(
        category="skills",
        fact_key=key,
        value=value,
        source_type="user",
        visibility=visibility,
        actor="test",
    )
    if status != "pending":
        fact = service.set_profile_fact_status(fact["id"], status, actor="test")
    return fact


def test_resume_requires_preparing_and_uses_only_confirmed_resume_facts(tmp_path):
    from docx import Document

    service = _service(tmp_path)
    job = _job(service)
    confirmed = _fact(service, "cell_culture", "完成NK细胞复苏、计数与CCK-8检测")
    _fact(service, "invented_internship", "某药企研发实习", status="pending")
    _fact(service, "private_note", "私人信息", visibility="private")

    with pytest.raises(DomainConflictError):
        service.generate_resume(job["id"], actor="test")

    service.transition_application(job["id"], "preparing", actor="test")
    result = service.generate_resume(job["id"], actor="test")

    output = Path(result["file_path"])
    assert output.is_file()
    assert output.suffix == ".docx"
    assert result["fact_ids"] == [confirmed["id"]]
    assert result["content_hash"]

    document = Document(output)
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "完成NK细胞复苏、计数与CCK-8检测" in text
    assert "某药企研发实习" not in text
    assert "私人信息" not in text
    assert "生物工艺工程师" in text
    assert service.list_resume_versions(job["id"])[0]["id"] == result["id"]


def test_imported_docx_is_copied_and_creates_pending_facts(tmp_path):
    from docx import Document

    input_path = tmp_path / "我的简历.docx"
    document = Document()
    document.add_heading("实验技能", level=1)
    document.add_paragraph("细胞培养与细胞计数")
    document.add_paragraph("CCK-8细胞活性检测")
    document.save(input_path)

    service = _service(tmp_path / "data")
    result = service.import_profile_document(input_path, actor="test")

    copied = Path(result["local_path"])
    assert copied.is_file()
    assert copied.resolve() != input_path.resolve()
    assert result["document_type"] == "docx"
    assert result["fact_count"] >= 2
    imported = [
        fact
        for fact in service.list_profile_facts()
        if fact["source_ref"] == result["id"]
    ]
    assert imported
    assert all(fact["status"] == "pending" for fact in imported)
    assert "细胞培养" in json.dumps(imported, ensure_ascii=False)


def test_profile_import_rejects_unsupported_or_oversized_files(tmp_path):
    service = _service(tmp_path / "data")
    text_path = tmp_path / "resume.txt"
    text_path.write_text("not supported", encoding="utf-8")
    with pytest.raises(DomainValidationError):
        service.import_profile_document(text_path, actor="test")


def test_application_export_has_four_sheets_and_clickable_links(tmp_path):
    service = _service(tmp_path)
    job = _job(service, status="preparing")
    _fact(service, "cell_culture", "细胞培养")
    service.match_job(job["id"], actor="test")
    resume = service.generate_resume(job["id"], actor="test")

    result = service.export_application_workbook(actor="test")
    output = Path(result["file_path"])
    assert output.is_file()
    assert output.suffix == ".xlsx"
    assert result["sheet_names"] == ["投递总表", "候选岗位", "本周行动", "数据字典"]

    with ZipFile(output) as archive:
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
        relationships = "\n".join(
            archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.startswith("xl/worksheets/_rels/")
        )
    for name in result["sheet_names"]:
        assert name in workbook_xml
    assert "https://jobs.example.test/detail/1" in relationships
    assert "https://jobs.example.test/apply/1" in relationships
    assert "https://jobs.example.test/careers" in relationships
    assert Path(resume["file_path"]).name in relationships
