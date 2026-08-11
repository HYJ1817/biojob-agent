"""Bounded RSS and Atom job feed adapter."""

from __future__ import annotations

from collections.abc import Mapping
import re
from xml.etree import ElementTree

from biojob.domain import RawJob
from biojob.sources.base import (
    SourceConfigurationError,
    SourceFetchError,
    SourceSecurityError,
    require_config_string,
)
from biojob.sources.http import SafeHttpClient
from biojob.sources.public_page import _clean_html_text


_XML_CONTENT_TYPES = {
    "application/xml",
    "text/xml",
    "application/rss+xml",
    "application/atom+xml",
}
_UNSAFE_XML_PATTERN = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)\b", re.I)
_MAX_ENTRIES = 500


class FeedJobAdapter:
    """Parse simple RSS 2.0 or Atom feeds without resolving XML entities."""

    adapter_type = "feed"

    def __init__(self, http: SafeHttpClient | None = None) -> None:
        self.http = http or SafeHttpClient()

    def fetch(self, config: Mapping[str, object]) -> list[RawJob]:
        source_url = require_config_string(config, "url")
        company_name = require_config_string(config, "company_name")
        assert source_url is not None
        assert company_name is not None
        response = self.http.get(source_url)
        if response.content_type not in _XML_CONTENT_TYPES:
            raise SourceFetchError("feed source must return RSS, Atom, or XML")
        if _UNSAFE_XML_PATTERN.search(response.content):
            raise SourceSecurityError("feed XML must not contain a DTD or entity")
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise SourceFetchError(f"feed XML could not be parsed: {exc}") from exc
        root_name = _local_name(root.tag)
        if root_name == "rss":
            entries = [node for node in root.iter() if _local_name(node.tag) == "item"]
        elif root_name == "feed":
            entries = [node for node in root.iter() if _local_name(node.tag) == "entry"]
        else:
            raise SourceFetchError("feed root must be RSS or Atom")
        jobs: list[RawJob] = []
        for entry in entries[:_MAX_ENTRIES]:
            title = _child_text(entry, "title")
            link = _entry_link(entry)
            if not title or not link:
                continue
            try:
                detail_url = self.http.validate_public_url(link)
            except (SourceFetchError, SourceSecurityError):
                continue
            description = _child_text(entry, "description") or _child_text(
                entry, "summary"
            )
            published = (
                _child_text(entry, "pubDate")
                or _child_text(entry, "published")
                or _child_text(entry, "updated")
            )
            external_id = _child_text(entry, "guid") or _child_text(entry, "id")
            jobs.append(
                RawJob(
                    company_name=company_name,
                    title=title,
                    detail_url=detail_url,
                    jd_text=_clean_html_text(description),
                    external_id=external_id,
                    published_at=published,
                )
            )
        return jobs


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ElementTree.Element, name: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == name:
            value = "".join(child.itertext()).strip()
            return value[:50_000] or None
    return None


def _entry_link(entry: ElementTree.Element) -> str | None:
    for child in entry:
        if _local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        if href and (child.attrib.get("rel", "alternate") == "alternate"):
            return href.strip() or None
        if child.text and child.text.strip():
            return child.text.strip()
    return None
