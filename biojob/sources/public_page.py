"""Conservative parser for public company recruitment pages."""

from __future__ import annotations

from collections.abc import Mapping
from html.parser import HTMLParser
import json
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from biojob.domain import RawJob
from biojob.sources.base import (
    SourceConfigurationError,
    SourceFetchError,
    SourceSecurityError,
    require_config_string,
)
from biojob.sources.http import SafeHttpClient


_SIGNALS = ("招聘", "职位", "岗位", "校招", "job", "career", "recruit")
_MAX_TEXT = 50_000
_MAX_JOBS = 500


class PublicPageAdapter:
    """Extract only structured JobPosting data or clearly signalled links."""

    adapter_type = "public_page"

    def __init__(self, http: SafeHttpClient | None = None) -> None:
        self.http = http or SafeHttpClient()

    def fetch(self, config: Mapping[str, object]) -> list[RawJob]:
        source_url = require_config_string(config, "url")
        assert source_url is not None
        fallback_company = require_config_string(config, "company_name", optional=True)
        response = self.http.get(source_url)
        if response.content_type not in {"text/html", "application/xhtml+xml"}:
            raise SourceFetchError("public page source must return HTML")
        parser = _RecruitmentHtmlParser()
        try:
            parser.feed(response.text)
            parser.close()
        except Exception as exc:
            raise SourceFetchError(
                f"public page HTML could not be parsed: {exc}"
            ) from exc

        jobs: list[RawJob] = []
        for raw_json in parser.json_ld_scripts:
            try:
                document = json.loads(raw_json)
            except (TypeError, ValueError):
                continue
            for item in _walk_json_ld(document):
                job = self._job_from_json_ld(
                    item,
                    base_url=response.url,
                    fallback_company=fallback_company,
                )
                if job is not None:
                    jobs.append(job)
                    if len(jobs) >= _MAX_JOBS:
                        return _dedupe_jobs(jobs)

        if fallback_company is not None:
            for anchor in parser.anchors:
                label = _clean_text(anchor["text"] or anchor["title"])
                href = anchor["href"].strip()
                if not label or not _has_signal(label):
                    continue
                resolved = urljoin(response.url, href)
                if not _has_signal(urlsplit(resolved).path):
                    continue
                try:
                    detail_url = self.http.validate_public_url(resolved)
                except (SourceFetchError, SourceSecurityError):
                    continue
                jobs.append(
                    RawJob(
                        company_name=fallback_company,
                        title=label,
                        detail_url=detail_url,
                        careers_url=response.url,
                    )
                )
                if len(jobs) >= _MAX_JOBS:
                    break
        return _dedupe_jobs(jobs)

    def _job_from_json_ld(
        self,
        item: Mapping[str, Any],
        *,
        base_url: str,
        fallback_company: str | None,
    ) -> RawJob | None:
        if not _is_job_posting(item.get("@type")):
            return None
        title = _string_value(item.get("title"))
        organization = item.get("hiringOrganization")
        company = (
            _string_value(organization.get("name"))
            if isinstance(organization, Mapping)
            else None
        ) or fallback_company
        if not title or not company:
            return None
        raw_url = _string_value(item.get("url")) or base_url
        try:
            detail_url = self.http.validate_public_url(urljoin(base_url, raw_url))
        except (SourceFetchError, SourceSecurityError):
            return None
        application_url = _string_value(item.get("applicationUrl"))
        apply_url = None
        if application_url:
            try:
                apply_url = self.http.validate_public_url(
                    urljoin(base_url, application_url)
                )
            except (SourceFetchError, SourceSecurityError):
                apply_url = None
        description = _clean_html_text(_string_value(item.get("description")))
        return RawJob(
            company_name=company,
            title=title,
            detail_url=detail_url,
            city=_job_city(item.get("jobLocation")),
            jd_text=description,
            apply_url=apply_url,
            published_at=_string_value(item.get("datePosted")),
            deadline_at=_string_value(item.get("validThrough")),
            recruitment_type=_string_value(item.get("employmentType")),
        )


class _RecruitmentHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.json_ld_scripts: list[str] = []
        self.anchors: list[dict[str, str]] = []
        self._script_is_json_ld = False
        self._script_parts: list[str] = []
        self._anchor: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        lowered = tag.lower()
        if lowered == "script":
            self._script_is_json_ld = (
                attributes.get("type", "").lower() == "application/ld+json"
            )
            self._script_parts = []
        elif lowered == "a":
            self._anchor = {
                "href": attributes.get("href", ""),
                "title": attributes.get("title", ""),
                "text": "",
            }

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "script":
            if self._script_is_json_ld:
                self.json_ld_scripts.append("".join(self._script_parts)[:_MAX_TEXT])
            self._script_is_json_ld = False
            self._script_parts = []
        elif lowered == "a" and self._anchor is not None:
            if self._anchor["href"]:
                self.anchors.append(self._anchor)
            self._anchor = None

    def handle_data(self, data: str) -> None:
        if self._script_is_json_ld:
            self._script_parts.append(data)
        if self._anchor is not None:
            self._anchor["text"] += data


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def _walk_json_ld(value: Any):
    if isinstance(value, list):
        for item in value:
            yield from _walk_json_ld(item)
    elif isinstance(value, Mapping):
        yield value
        graph = value.get("@graph")
        if graph is not None:
            yield from _walk_json_ld(graph)


def _is_job_posting(value: Any) -> bool:
    if isinstance(value, str):
        return value.casefold() == "jobposting"
    if isinstance(value, list):
        return any(_is_job_posting(item) for item in value)
    return False


def _string_value(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _job_city(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            city = _job_city(item)
            if city:
                return city
        return None
    if not isinstance(value, Mapping):
        return None
    address = value.get("address")
    if isinstance(address, Mapping):
        return _string_value(address.get("addressLocality"))
    return None


def _clean_html_text(value: str | None) -> str | None:
    if value is None:
        return None
    parser = _TextExtractor()
    parser.feed(value[:_MAX_TEXT])
    parser.close()
    return _clean_text(" ".join(parser.parts)) or None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()[:_MAX_TEXT]


def _has_signal(value: str) -> bool:
    folded = value.casefold()
    return any(signal in folded for signal in _SIGNALS)


def _dedupe_jobs(jobs: list[RawJob]) -> list[RawJob]:
    seen: set[tuple[str, str]] = set()
    result: list[RawJob] = []
    for job in jobs:
        key = (job.detail_url, job.title)
        if key not in seen:
            seen.add(key)
            result.append(job)
    return result
