from __future__ import annotations

from datetime import datetime, timezone

import pytest

from biojob.matching import MATCH_RULE_VERSION, match_job


def _fact(category: str, key: str, value):
    return {
        "id": f"{category}-{key}",
        "category": category,
        "fact_key": key,
        "value": value,
        "status": "confirmed",
        "visibility": "both",
    }


def _job(**overrides):
    job = {
        "id": "job-1",
        "title": "生物工艺工程师",
        "direction": "生物工艺",
        "city": "济南",
        "recruitment_type": "2027届校园招聘",
        "education_requirement": "本科及以上",
        "major_requirement": "生物工程、生物技术相关专业",
        "jd_text": "负责细胞培养、发酵工艺和GMP生产记录，应届本科生可投。",
        "lifecycle_status": "open",
        "deadline_at": "2030-12-31T23:59:59Z",
        "company": {"name": "示例生物", "city": "济南", "type": "生物医药"},
    }
    job.update(overrides)
    return job


def _facts():
    return [
        _fact("education", "degree", "本科"),
        _fact("education", "major", "生物工程"),
        _fact("education", "graduation_year", 2027),
        _fact("skills", "cell_culture", "细胞培养"),
        _fact("skills", "fermentation", "发酵工程"),
        _fact("preference", "target_directions", ["生物工艺", "制药生产", "QA", "QC"]),
        _fact("preference", "cities", ["济南", "青岛", "上海"]),
    ]


def test_match_returns_weighted_evidence_and_no_unsupported_claims():
    report = match_job(_job(), _facts(), now=datetime(2026, 8, 12, tzinfo=timezone.utc))

    assert report["rule_version"] == MATCH_RULE_VERSION
    assert report["blocked"] is False
    assert 80 <= report["score"] <= 100
    assert report["level"] == "priority"
    assert [dimension["weight"] for dimension in report["dimensions"]] == [25, 20, 25, 10, 10, 10]
    assert sum(dimension["score"] for dimension in report["dimensions"]) == report["score"]
    assert any("细胞培养" in evidence for evidence in report["dimensions"][2]["job_evidence"])
    assert any("细胞培养" in evidence for evidence in report["dimensions"][2]["fact_evidence"])
    assert all("论文" not in str(value) for value in report.values())


@pytest.mark.parametrize(
    ("overrides", "expected_rule"),
    [
        ({"education_requirement": "仅限博士研究生"}, "degree"),
        ({"education_requirement": "硕士研究生及以上"}, "degree"),
        ({"jd_text": "要求3年全职相关工作经验。"}, "experience"),
        ({"recruitment_type": "2026届校园招聘"}, "graduation_cohort"),
        ({"title": "药物合成研究员", "direction": "药物合成"}, "excluded_direction"),
        ({"lifecycle_status": "closed"}, "availability"),
        ({"deadline_at": "2026-08-01T00:00:00Z"}, "availability"),
    ],
)
def test_hard_rules_block_ineligible_jobs(overrides, expected_rule):
    report = match_job(_job(**overrides), _facts(), now=datetime(2026, 8, 12, tzinfo=timezone.utc))

    assert report["blocked"] is True
    assert report["level"] == "blocked"
    assert report["recommendation"] == "不建议投递"
    assert expected_rule in {rule["rule"] for rule in report["hard_rules"] if rule["blocked"]}


def test_preferred_degree_or_experience_is_a_risk_not_a_block():
    report = match_job(
        _job(
            education_requirement="本科及以上，硕士优先",
            jd_text="负责发酵生产；有相关经验者优先，应届生可投。",
        ),
        _facts(),
        now=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )

    assert report["blocked"] is False
    assert any("优先" in risk for risk in report["risks"])


def test_missing_evidence_is_explicit_and_reduces_confidence():
    report = match_job(
        _job(
            direction=None,
            city=None,
            education_requirement=None,
            major_requirement=None,
            jd_text=None,
            recruitment_type=None,
            company={"name": "示例生物", "city": None, "type": None},
        ),
        [],
        now=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )

    assert report["blocked"] is False
    assert report["confidence"] == "low"
    assert report["score"] < 50
    assert "缺少完整JD" in report["gaps"]
    assert any("未在JD找到" in evidence for d in report["dimensions"] for evidence in d["job_evidence"])


def test_only_confirmed_matching_visible_facts_are_used_defensively():
    facts = _facts() + [
        {**_fact("skills", "paper", "顶级论文"), "status": "pending"},
        {**_fact("skills", "enterprise", "药企实习"), "visibility": "private"},
    ]

    report = match_job(_job(), facts, now=datetime(2026, 8, 12, tzinfo=timezone.utc))
    serialized = str(report)

    assert "顶级论文" not in serialized
    assert "药企实习" not in serialized
