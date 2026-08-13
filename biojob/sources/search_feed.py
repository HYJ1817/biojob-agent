"""Public search feeds filtered for undergraduate bioengineering roles."""

from __future__ import annotations

import base64
from collections.abc import Mapping
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from biojob.domain import RawJob
from biojob.sources.base import SourceFetchError, require_config_string
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
)
_TRACKING_KEYS = {"fbclid", "gclid", "msclkid"}
_TITLE_SEPARATOR = re.compile(r"\s+(?:[-–—|｜])\s+")


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
        if response.content_type not in _XML_CONTENT_TYPES:
            raise SourceFetchError("search feed source must return RSS, Atom, or XML")
        jobs: list[RawJob] = []
        for entry in parse_feed_entries(response.content):
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
        if not any(term.upper() in upper for term in _POSITIVE_TERMS):
            return None
        detail_url = self.http.validate_external_link(
            _normalize_result_url(entry.link)
        )
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
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(kept_query), "")
    )
