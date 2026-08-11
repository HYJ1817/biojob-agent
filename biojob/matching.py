"""Deterministic, evidence-backed matching for undergraduate BioJob users."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
import re
from typing import Any


MATCH_RULE_VERSION = "biojob-undergraduate-v2"

_DIMENSIONS = (
    ("direction", "岗位方向", 25),
    ("education_major", "学历与专业", 20),
    ("skills", "实验与工艺技能", 25),
    ("cohort_experience", "届别与经验", 10),
    ("region_company", "地区与企业", 10),
    ("growth_quality", "成长与岗位质量", 10),
)
_EXCLUDED_DIRECTIONS = ("药物合成", "有机合成", "临床项目经理", "医药销售", "医疗器械销售")
_QUALITY_TERMS = ("GMP", "工艺", "生产", "发酵", "细胞培养", "质量", "QA", "QC", "培训", "轮岗")
_SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "细胞培养": ("细胞培养", "细胞复苏", "细胞计数"),
    "发酵工程": ("发酵", "发酵工程", "发酵工艺"),
    "CCK-8": ("CCK-8", "CCK8", "细胞活性"),
    "凝胶电泳": ("凝胶电泳", "电泳"),
    "转膜": ("转膜", "Western blot", "WB"),
    "微生物培养": ("微生物培养", "菌株", "微生物"),
    "Excel": ("Excel", "数据整理", "数据分析"),
}


def match_job(
    job: Mapping[str, Any],
    profile_facts: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return an explainable match report without inventing absent evidence."""

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    facts = [fact for fact in profile_facts if _fact_is_usable(fact)]
    fact_values = [_display_value(fact.get("value")) for fact in facts]
    fact_text = "\n".join(value for value in fact_values if value)
    job_text = _job_text(job)

    hard_rules, risks = _evaluate_hard_rules(job, job_text, facts, current_time)
    blocked = any(rule["blocked"] for rule in hard_rules)
    dimensions = _score_dimensions(job, job_text, facts, fact_text)
    score = round(sum(dimension["score"] for dimension in dimensions), 1)

    gaps: list[str] = []
    if not _clean(job.get("jd_text")):
        gaps.append("缺少完整JD")
    for dimension in dimensions:
        if dimension["score"] < dimension["weight"] * 0.5:
            gaps.append(f"{dimension['label']}证据不足")
    for rule in hard_rules:
        if rule["blocked"]:
            gaps.append(rule["message"])

    confidence_points = sum(
        bool(_clean(job.get(field)))
        for field in (
            "jd_text",
            "education_requirement",
            "major_requirement",
            "recruitment_type",
            "city",
            "direction",
        )
    ) + min(3, len(facts))
    confidence = "high" if confidence_points >= 7 else "medium" if confidence_points >= 4 else "low"

    if blocked:
        level = "blocked"
        recommendation = "不建议投递"
    elif score >= 80:
        level = "priority"
        recommendation = "优先投递"
    elif score >= 65:
        level = "suggested"
        recommendation = "建议投递"
    elif score >= 50:
        level = "cautious"
        recommendation = "谨慎评估"
    else:
        level = "low"
        recommendation = "暂不优先"

    return {
        "score": score,
        "level": level,
        "recommendation": recommendation,
        "blocked": blocked,
        "hard_rules": hard_rules,
        "dimensions": dimensions,
        "gaps": _unique(gaps),
        "risks": _unique(risks),
        "confidence": confidence,
        "rule_version": MATCH_RULE_VERSION,
    }


def _evaluate_hard_rules(
    job: Mapping[str, Any],
    job_text: str,
    facts: list[Mapping[str, Any]],
    now: datetime,
) -> tuple[list[dict[str, Any]], list[str]]:
    requirements = " ".join(
        filter(None, (_clean(job.get("education_requirement")), _clean(job.get("jd_text"))))
    )
    degree_block = bool(
        re.search(r"(?:仅限|要求|学历[:：]?\s*)(?:博士|硕士)|(?:博士|硕士)(?:研究生)?及以上", requirements)
    )
    if "本科及以上" in requirements and ("硕士优先" in requirements or "博士优先" in requirements):
        degree_block = False
    risks: list[str] = []
    if re.search(r"(?:硕士|博士|经验).{0,8}优先|有.{0,8}经验者优先", requirements):
        risks.append("JD包含学历或经验优先条件，但不是硬性门槛")

    experience_block = False
    experience_match = re.search(r"([1-9]\d*)\s*年(?:及以上|以上)?[^。；;\n]{0,16}(?:全职|工作|相关)?经验", job_text)
    if experience_match:
        sentence_start = max(job_text.rfind("。", 0, experience_match.start()), 0)
        sentence_end = job_text.find("。", experience_match.end())
        sentence = job_text[sentence_start : sentence_end if sentence_end >= 0 else len(job_text)]
        experience_block = "优先" not in sentence

    grad_year = _graduation_year(facts)
    cohort_years = {int(value) for value in re.findall(r"(20\d{2})届", _clean(job.get("recruitment_type")) or job_text)}
    cohort_block = bool(grad_year and cohort_years and grad_year not in cohort_years)

    title_direction = " ".join(filter(None, (_clean(job.get("title")), _clean(job.get("direction")))))
    excluded = next((term for term in _EXCLUDED_DIRECTIONS if term.lower() in title_direction.lower()), None)

    lifecycle = (_clean(job.get("lifecycle_status")) or "unknown").lower()
    deadline = _parse_datetime(job.get("deadline_at"))
    unavailable = lifecycle == "closed" or (deadline is not None and deadline < now.astimezone(timezone.utc))

    rules = [
        _hard_rule("degree", degree_block, "岗位明确要求硕士/博士学历", requirements or "未在JD找到学历硬门槛"),
        _hard_rule("experience", experience_block, "岗位明确要求多年全职经验", experience_match.group(0) if experience_match else "未在JD找到全职经验硬门槛"),
        _hard_rule("graduation_cohort", cohort_block, "招聘届别与2027届身份不符", f"招聘届别：{sorted(cohort_years)}" if cohort_years else "未在JD找到招聘届别"),
        _hard_rule("excluded_direction", excluded is not None, f"岗位属于暂不重点方向：{excluded}" if excluded else "未命中排除方向", title_direction or "未在JD找到岗位方向"),
        _hard_rule("availability", unavailable, "岗位已关闭或截止日期已过", f"状态：{lifecycle}；截止：{_clean(job.get('deadline_at')) or '未在JD找到'}"),
    ]
    return rules, risks


def _score_dimensions(
    job: Mapping[str, Any],
    job_text: str,
    facts: list[Mapping[str, Any]],
    fact_text: str,
) -> list[dict[str, Any]]:
    preferred_directions = _fact_tokens(facts, "target_directions")
    direction_text = " ".join(filter(None, (_clean(job.get("title")), _clean(job.get("direction")), job_text)))
    direction_hits = [term for term in preferred_directions if term.lower() in direction_text.lower()]

    degree = _fact_value(facts, "degree")
    major = _fact_value(facts, "major")
    education_requirements = " ".join(
        filter(None, (_clean(job.get("education_requirement")), _clean(job.get("major_requirement")), job_text))
    )
    education_hits = [value for value in (degree, major) if value and value.lower() in education_requirements.lower()]

    skill_hits: list[str] = []
    for fact in facts:
        if fact.get("category") not in {"skills", "laboratory", "experiment", "data"}:
            continue
        display = _display_value(fact.get("value"))
        aliases = _SKILL_ALIASES.get(display, (display,)) if display else ()
        if any(alias and alias.lower() in job_text.lower() for alias in aliases):
            skill_hits.append(display)

    grad_year = _graduation_year(facts)
    cohort_hit = bool(grad_year and (f"{grad_year}届" in job_text or "应届" in job_text))

    preferred_cities = _fact_tokens(facts, "cities")
    city = _clean(job.get("city")) or _clean((job.get("company") or {}).get("city"))
    city_hits = [preferred for preferred in preferred_cities if city and preferred.lower() in city.lower()]

    quality_hits = [term for term in _QUALITY_TERMS if term.lower() in job_text.lower()]

    raw = (
        (25 if direction_hits else 12 if _clean(job.get("direction")) and not preferred_directions else 0, direction_hits, preferred_directions),
        (min(20, len(education_hits) * 10), education_hits, [value for value in (degree, major) if value]),
        (min(25, len(_unique(skill_hits)) * 12.5), _unique(skill_hits), _unique(skill_hits)),
        (10 if cohort_hit else 0, [f"{grad_year}届/应届匹配"] if cohort_hit else [], [f"毕业年份：{grad_year}"] if grad_year else []),
        (10 if city_hits else 0, [f"工作城市：{city}"] if city else [], [f"意向城市：{hit}" for hit in city_hits]),
        (min(10, len(quality_hits) * 2.5), quality_hits, []),
    )
    dimensions = []
    for (key, label, weight), (score, job_evidence, fact_evidence) in zip(_DIMENSIONS, raw, strict=True):
        dimensions.append(
            {
                "key": key,
                "label": label,
                "weight": weight,
                "score": round(float(score), 1),
                "job_evidence": job_evidence or ["未在JD找到可计分证据"],
                "fact_evidence": fact_evidence or ["未找到对应的已确认个人事实"],
            }
        )
    return dimensions


def _hard_rule(rule: str, blocked: bool, message: str, evidence: str) -> dict[str, Any]:
    return {"rule": rule, "blocked": blocked, "message": message, "evidence": evidence}


def _fact_is_usable(fact: Mapping[str, Any]) -> bool:
    return fact.get("status") == "confirmed" and fact.get("visibility") in {"matching", "both"}


def _fact_value(facts: Iterable[Mapping[str, Any]], key: str) -> str | None:
    for fact in facts:
        if fact.get("fact_key") == key:
            return _display_value(fact.get("value")) or None
    return None


def _fact_tokens(facts: Iterable[Mapping[str, Any]], key: str) -> list[str]:
    for fact in facts:
        if fact.get("fact_key") != key:
            continue
        value = fact.get("value")
        if isinstance(value, list):
            return [_display_value(item) for item in value if _display_value(item)]
        display = _display_value(value)
        return [display] if display else []
    return []


def _graduation_year(facts: Iterable[Mapping[str, Any]]) -> int | None:
    value = _fact_value(facts, "graduation_year")
    try:
        return int(value) if value else None
    except ValueError:
        return None


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "、".join(filter(None, (_display_value(item) for item in value)))
    if isinstance(value, Mapping):
        return "、".join(filter(None, (_display_value(item) for item in value.values())))
    return ""


def _job_text(job: Mapping[str, Any]) -> str:
    company = job.get("company") if isinstance(job.get("company"), Mapping) else {}
    values = (
        job.get("title"),
        job.get("direction"),
        job.get("city"),
        job.get("recruitment_type"),
        job.get("education_requirement"),
        job.get("major_requirement"),
        job.get("jd_text"),
        company.get("type"),
        company.get("city"),
    )
    return "\n".join(value for value in (_clean(item) for item in values) if value)


def _parse_datetime(value: Any) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
