"""Public search feeds filtered for undergraduate bioengineering roles."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from html.parser import HTMLParser
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from biojob.domain import RawJob
from biojob.sources.base import SourceFetchError, require_config_string
from biojob.sources.base import SourceSecurityError
from biojob.sources.feed import _XML_CONTENT_TYPES, FeedEntry, parse_feed_entries
from biojob.sources.http import SafeHttpClient
from biojob.sources.public_page import _clean_html_text


_POSITIVE_TERMS = (
    "生物",
    "制药",
    "发酵",
    "微生物",
    "细胞培养",
    "生产技术",
    "生物工艺",
    "工艺工程",
    "实验员",
    "生物分析",
    "研发助理",
    "质量",
    "QA",
    "QC",
    "GMP",
)
_HARD_EXCLUSIONS = (
    "博士后",
    "仅限博士",
    "高级经理",
    "总监",
    "医药销售",
    "临床项目经理",
    "药物合成",
    "合成研究员",
    "CRA",
)
_TRACKING_KEYS = {"fbclid", "gclid", "msclkid"}
_RECRUITMENT_TERMS = ("招聘", "校招", "应届", "职位", "岗位", "实习")
_TITLE_SEPARATOR = re.compile(r"\s+(?:[-–—|｜])\s+")
_AGGREGATOR_NAMES = (
    "智联招聘",
    "BOSS直聘",
    "猎聘",
    "前程无忧",
    "齐鲁人才网",
    "职友集",
)
_COHORT_YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
_RELEVANT_COHORT_YEARS = {2026, 2027}


class SearchFeedAdapter:
    adapter_type = "search_feed"

    def __init__(self, http: SafeHttpClient | None = None) -> None:
        self.http = http or SafeHttpClient()

    def fetch(self, config: Mapping[str, object]) -> list[RawJob]:
        source_url = require_config_string(config, "url")
        require_config_string(config, "query_label")
        assert source_url is not None
        reviewed_hosts = _runtime_reviewed_hosts(config)
        response = self.http.get(source_url, reviewed_hosts=reviewed_hosts)
        if response.content_type in _XML_CONTENT_TYPES:
            entries = parse_feed_entries(response.content)
        elif response.content_type in {"text/html", "application/xhtml+xml"}:
            if urlsplit(response.url).hostname != "www.so.com":
                raise SourceFetchError(
                    "search HTML must use a reviewed HTML search provider"
                )
            entries = _parse_so_search_results(response.text)
        else:
            raise SourceFetchError("search source must return RSS, Atom, XML, or HTML")
        jobs: list[RawJob] = []
        for entry in entries:
            job = self._job_from_entry(entry)
            if job is not None:
                jobs.append(job)
        return jobs

    def _job_from_entry(self, entry: FeedEntry) -> RawJob | None:
        description = _clean_html_text(entry.description)
        content = f"{entry.title}\n{description or ''}"
        upper = content.upper()
        if any(term in content for term in _HARD_EXCLUSIONS):
            return None
        years = {int(match) for match in _COHORT_YEAR.findall(content)}
        if years and years.isdisjoint(_RELEVANT_COHORT_YEARS):
            return None
        if not any(term.upper() in upper for term in _POSITIVE_TERMS):
            return None
        try:
            detail_url = self.http.validate_external_link(
                _normalize_result_url(entry.link)
            )
        except (SourceFetchError, SourceSecurityError):
            return None
        company, title = _split_company_and_title(entry.title)
        if company is None:
            company = f"待核验 · {urlsplit(detail_url).hostname}"
        return RawJob(
            company_name=company,
            title=title,
            detail_url=detail_url,
            jd_text=description,
            external_id=entry.external_id,
            published_at=entry.published,
            recruitment_type="校招（待核验）",
        )


class _SoSearchParser(HTMLParser):
    """Collect title links only from 360 Search result headings."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[FeedEntry] = []
        self._heading_depth = 0
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.casefold()
        if lowered == "h3":
            self._heading_depth += 1
        elif lowered == "a" and self._heading_depth and self._href is None:
            attributes = {key.casefold(): value or "" for key, value in attrs}
            self._href = attributes.get("href") or None
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered == "a" and self._href is not None:
            title = " ".join("".join(self._parts).split())
            if title and any(term in title for term in _RECRUITMENT_TERMS):
                self.entries.append(FeedEntry(title=title, link=self._href))
            self._href = None
            self._parts = []
        elif lowered == "h3" and self._heading_depth:
            self._heading_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)


def _parse_so_search_results(html: str) -> list[FeedEntry]:
    parser = _SoSearchParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:
        raise SourceFetchError(f"search HTML could not be parsed: {exc}") from exc
    return parser.entries


def _runtime_reviewed_hosts(config: Mapping[str, object]) -> frozenset[str]:
    value = config.get("_reviewed_hosts", frozenset())
    if isinstance(value, (list, tuple, set, frozenset)) and all(
        isinstance(host, str) and host for host in value
    ):
        return frozenset(value)
    raise SourceFetchError("reviewed source host policy is invalid")


def _split_company_and_title(value: str) -> tuple[str | None, str]:
    parts = [part.strip() for part in _TITLE_SEPARATOR.split(value, maxsplit=1)]
    if len(parts) == 2 and parts[0] and parts[1]:
        if any(name in parts[1] for name in _AGGREGATOR_NAMES):
            return None, value.strip()
        return parts[0], parts[1]
    return None, value.strip()


def _normalize_result_url(value: str) -> str:
    parsed = urlsplit(value)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if parsed.hostname and parsed.hostname.casefold().endswith("bing.com"):
        target = query.get("url")
        encoded = query.get("u")
        if target:
            value = unquote(target)
            parsed = urlsplit(value)
        elif encoded and encoded.startswith("a1"):
            payload = encoded[2:]
            payload += "=" * (-len(payload) % 4)
            try:
                value = base64.urlsafe_b64decode(payload).decode("utf-8")
                parsed = urlsplit(value)
            except (ValueError, UnicodeDecodeError):
                pass
    kept_query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in _TRACKING_KEYS
    ]
    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        urlencode(kept_query),
        "",
    ))
