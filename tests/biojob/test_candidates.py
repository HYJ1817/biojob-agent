from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json

import pytest

from biojob.database import BioJobDatabase
from biojob.domain import (
    CandidateDecision,
    DomainConflictError,
    DomainDataCorruptionError,
    DomainNotFoundError,
    RawJob,
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


def add_source(
    database,
    source_id="source-qilu",
    name="齐鲁制药官网",
    adapter_type="public_page",
):
    with closing(database.connect()) as connection:
        now = "2026-08-12T00:00:00+00:00"
        connection.execute(
            "INSERT INTO sources "
            "(id, name, adapter_type, config_json, description, created_at, updated_at) "
            "VALUES (?, ?, ?, '{}', '', ?, ?)",
            (source_id, name, adapter_type, now, now),
        )
    return source_id


def raw_job(**overrides):
    values = {
        "company_name": "齐鲁制药",
        "title": "生物工艺工程师",
        "detail_url": "https://example.test/jobs/bioprocess-1",
        "apply_url": "https://example.test/apply/bioprocess-1",
        "careers_url": "https://example.test/careers",
        "city": "济南",
        "jd_text": "本科应届生，负责生物工艺、发酵和GMP生产。",
        "external_id": "bioprocess-1",
        "published_at": "2026-08-01",
        "deadline_at": "2026-10-01",
        "recruitment_type": "校招",
    }
    values.update(overrides)
    return RawJob(**values)


def table_count(database, table):
    with closing(database.connect()) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_candidate_decision_enum_has_persisted_values():
    assert {decision.value for decision in CandidateDecision} == {
        "pending",
        "kept",
        "ignored",
        "later",
        "error",
    }


def test_ingest_creates_reviewable_candidate_without_application(database, service):
    source_id = add_source(database)

    candidate = service.ingest_candidate(
        raw_job(), source_id=source_id, actor="source:qilu"
    )

    assert candidate["company_name"] == "齐鲁制药"
    assert candidate["title"] == "生物工艺工程师"
    assert candidate["decision"] == "pending"
    assert candidate["source_count"] == 1
    assert candidate["snapshot_count"] == 1
    assert candidate["application"] is None
    assert candidate["links"] == {
        "detail": "https://example.test/jobs/bioprocess-1",
        "apply": "https://example.test/apply/bioprocess-1",
        "careers": "https://example.test/careers",
    }
    assert 0 <= candidate["match"]["score"] <= 100
    assert candidate["match"]["recommendation"] == "优先推荐"
    assert "生物工艺" in candidate["match"]["evidence"]["positive_terms"]
    assert table_count(database, "applications") == 0
    assert table_count(database, "job_sources") == 1
    assert table_count(database, "job_snapshots") == 1
    assert table_count(database, "job_matches") == 1
    assert table_count(database, "candidate_decisions") == 1


def test_search_feed_candidate_is_marked_for_original_page_verification(
    database, service
):
    source_id = add_source(database, adapter_type="search_feed")

    candidate = service.ingest_candidate(
        raw_job(), source_id=source_id, actor="source:search"
    )

    assert candidate["needs_verification"] is True

    official_id = add_source(
        database,
        source_id="source-official",
        name="齐鲁制药官方招聘",
        adapter_type="public_page",
    )
    candidate = service.ingest_candidate(
        raw_job(
            title="QC实验员",
            detail_url="https://official.example.test/jobs/1",
            external_id="official-qc-1",
        ),
        source_id=official_id,
        actor="source:official",
    )

    assert candidate["needs_verification"] is False


def test_same_snapshot_is_idempotent_and_changed_jd_adds_snapshot(database, service):
    source_id = add_source(database)
    first = service.ingest_candidate(
        raw_job(), source_id=source_id, actor="source:qilu"
    )
    repeated = service.ingest_candidate(
        raw_job(), source_id=source_id, actor="source:qilu"
    )
    changed = service.ingest_candidate(
        raw_job(jd_text="本科应届生，负责细胞培养与质量控制。"),
        source_id=source_id,
        actor="source:qilu",
    )

    assert repeated["id"] == first["id"]
    assert changed["id"] == first["id"]
    assert table_count(database, "jobs") == 1
    assert table_count(database, "job_sources") == 1
    assert table_count(database, "job_snapshots") == 2
    assert table_count(database, "job_matches") == 2
    assert table_count(database, "candidate_decisions") == 1
    assert changed["jd_text"] == "本科应届生，负责细胞培养与质量控制。"


def test_nfkc_dedup_merges_cross_source_and_retains_links(database, service):
    first_source = add_source(database)
    second_source = add_source(database, "source-remegen", "荣昌生物官网")
    first = service.ingest_candidate(
        raw_job(), source_id=first_source, actor="source:qilu"
    )
    merged = service.ingest_candidate(
        raw_job(
            company_name=" 齐鲁制药 ",
            title="生物工艺工程师",
            city="济南　",
            recruitment_type="校招",
            detail_url="https://jobs.example.test/roles/99",
            apply_url="https://jobs.example.test/apply/99",
            external_id="99",
        ),
        source_id=second_source,
        actor="source:remegen",
    )

    assert merged["id"] == first["id"]
    assert merged["source_count"] == 2
    assert table_count(database, "jobs") == 1
    with closing(database.connect()) as connection:
        links = connection.execute(
            "SELECT detail_url, apply_url FROM job_sources ORDER BY source_id"
        ).fetchall()
    assert {tuple(link) for link in links} == {
        (
            "https://example.test/jobs/bioprocess-1",
            "https://example.test/apply/bioprocess-1",
        ),
        (
            "https://jobs.example.test/roles/99",
            "https://jobs.example.test/apply/99",
        ),
    }


def test_cross_source_same_detail_url_retains_both_source_attributions(
    database, service
):
    first_source = add_source(database)
    second_source = add_source(database, "source-feed", "公开招聘订阅")
    first = service.ingest_candidate(
        raw_job(), source_id=first_source, actor="source:qilu"
    )

    merged = service.ingest_candidate(
        raw_job(external_id="feed-copy"),
        source_id=second_source,
        actor="source:feed",
    )

    assert merged["id"] == first["id"]
    assert merged["source_count"] == 2
    with closing(database.connect()) as connection:
        source_ids = connection.execute(
            "SELECT source_id FROM job_sources WHERE job_id = ? ORDER BY source_id",
            (first["id"],),
        ).fetchall()
    assert [row[0] for row in source_ids] == ["source-feed", "source-qilu"]


def test_hard_gap_is_visible_and_candidate_is_not_deleted(database, service):
    source_id = add_source(database)
    candidate = service.ingest_candidate(
        raw_job(
            title="药物研发科学家",
            jd_text="仅限硕士或博士，负责药物合成。",
        ),
        source_id=source_id,
        actor="source:qilu",
    )

    assert candidate["match"]["recommendation"] == "不建议"
    assert set(candidate["match"]["evidence"]["hard_gaps"]) >= {
        "博士",
        "仅限硕士",
        "药物合成",
    }
    assert service.get_candidate(candidate["id"])["decision"] == "pending"


def test_filters_search_latest_candidate_state(database, service):
    source_id = add_source(database)
    production = service.ingest_candidate(
        raw_job(), source_id=source_id, actor="source:qilu"
    )
    quality = service.ingest_candidate(
        raw_job(
            title="QC实验员",
            detail_url="https://example.test/jobs/qc-2",
            apply_url=None,
            external_id="qc-2",
            city="烟台",
            jd_text="本科，负责QC质量检测与实验记录。",
        ),
        source_id=source_id,
        actor="source:qilu",
    )
    service.decide_candidate(quality["id"], "later", actor="user")

    assert [item["id"] for item in service.list_candidates()] == [production["id"]]
    assert [
        item["id"]
        for item in service.list_candidates(
            decision="later", query="QC", direction="质量", city="烟台"
        )
    ] == [quality["id"]]


def test_kept_creates_one_application_atomically_and_terminal_repeat_conflicts(
    database, service
):
    source_id = add_source(database)
    candidate = service.ingest_candidate(
        raw_job(), source_id=source_id, actor="source:qilu"
    )

    kept = service.decide_candidate(
        candidate["id"], "kept", actor="user", note="准备投递"
    )

    assert kept["decision"] == "kept"
    assert kept["application"]["status"] == "considering"
    assert kept["application"]["notes"] == "准备投递"
    assert table_count(database, "applications") == 1
    assert table_count(database, "application_events") == 1
    assert service.get_job(candidate["id"])["application"]["status"] == "considering"
    with pytest.raises(DomainConflictError):
        service.decide_candidate(candidate["id"], "kept", actor="user")
    assert table_count(database, "applications") == 1


def test_kept_rolls_back_decision_and_application_when_event_write_fails(
    database, service, monkeypatch
):
    source_id = add_source(database)
    candidate = service.ingest_candidate(
        raw_job(), source_id=source_id, actor="source:qilu"
    )

    def fail_event(*args, **kwargs):
        raise RuntimeError("synthetic event failure")

    monkeypatch.setattr(BioJobRepository, "insert_application_event", fail_event)
    with pytest.raises(RuntimeError, match="synthetic event failure"):
        service.decide_candidate(candidate["id"], "kept", actor="user")

    assert service.get_candidate(candidate["id"])["decision"] == "pending"
    assert table_count(database, "candidate_decisions") == 1
    assert table_count(database, "applications") == 0
    assert table_count(database, "application_events") == 0


@pytest.mark.parametrize("decision", ["ignored", "later", "error"])
def test_non_kept_decisions_do_not_create_application(database, service, decision):
    source_id = add_source(database)
    candidate = service.ingest_candidate(
        raw_job(), source_id=source_id, actor="source:qilu"
    )

    decided = service.decide_candidate(candidate["id"], decision, actor="user")

    assert decided["decision"] == decision
    assert decided["application"] is None
    assert table_count(database, "applications") == 0


def test_only_later_can_explicitly_return_to_pending(database, service):
    source_id = add_source(database)
    candidate = service.ingest_candidate(
        raw_job(), source_id=source_id, actor="source:qilu"
    )
    service.decide_candidate(candidate["id"], "later", actor="user")

    pending = service.decide_candidate(
        candidate["id"], CandidateDecision.PENDING, actor="user"
    )

    assert pending["decision"] == "pending"
    with pytest.raises(DomainConflictError):
        service.decide_candidate(candidate["id"], "pending", actor="user")


def test_unknown_source_and_candidate_fail_closed(database, service):
    with pytest.raises(DomainNotFoundError):
        service.ingest_candidate(
            raw_job(), source_id="missing-source", actor="source:test"
        )
    with pytest.raises(DomainNotFoundError):
        service.get_candidate("missing-job")


def test_concurrent_duplicate_ingestion_has_one_active_job(database):
    source_id = add_source(database)

    def ingest(_):
        return BioJobService(database).ingest_candidate(
            raw_job(), source_id=source_id, actor="source:qilu"
        )["id"]

    with ThreadPoolExecutor(max_workers=4) as executor:
        ids = list(executor.map(ingest, range(8)))

    assert len(set(ids)) == 1
    assert table_count(database, "jobs") == 1
    assert table_count(database, "job_snapshots") == 1
    assert table_count(database, "candidate_decisions") == 1


def test_soft_deleted_candidate_allows_replacement(database, service):
    source_id = add_source(database)
    first = service.ingest_candidate(
        raw_job(), source_id=source_id, actor="source:qilu"
    )
    with closing(database.connect()) as connection:
        connection.execute(
            "UPDATE jobs SET deleted_at = '2026-08-12T01:00:00+00:00' WHERE id = ?",
            (first["id"],),
        )

    replacement = service.ingest_candidate(
        raw_job(), source_id=source_id, actor="source:qilu"
    )

    assert replacement["id"] != first["id"]
    assert table_count(database, "jobs") == 2


@pytest.mark.parametrize("target", ["decision", "evidence_json"])
def test_corrupt_candidate_state_fails_closed(database, service, target):
    source_id = add_source(database)
    candidate = service.ingest_candidate(
        raw_job(), source_id=source_id, actor="source:qilu"
    )
    with closing(database.connect()) as connection:
        if target == "decision":
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute(
                "UPDATE candidate_decisions SET decision = 'surprise' WHERE job_id = ?",
                (candidate["id"],),
            )
        else:
            connection.execute(
                "UPDATE job_matches SET evidence_json = ? WHERE job_id = ?",
                (json.dumps({"score": float("nan")}), candidate["id"]),
            )

    with pytest.raises(DomainDataCorruptionError):
        service.get_candidate(candidate["id"])
