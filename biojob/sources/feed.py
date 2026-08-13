"""Bounded RSS and Atom job feed adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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


@dataclass(frozen=True)
class FeedEntry:
    title: str
    link: str
    description: str | None = None
    published: str | None = None
    external_id: str | None = None


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
        entries = parse_feed_entries(response.content)
        jobs: list[RawJob] = []
        for entry in entries:
            try:
                detail_url = self.http.validate_public_url(entry.link)
            except (SourceFetchError, SourceSecurityError):
                continue
            jobs.append(
                RawJob(
                    company_name=company_name,
                    title=entry.title,
                    detail_url=detail_url,
                    jd_text=_clean_html_text(entry.description),
                    external_id=entry.external_id,
                    published_at=entry.published,
                )
            )
        return jobs


def parse_feed_entries(content: bytes) -> list[FeedEntry]:
    if _UNSAFE_XML_PATTERN.search(content):
        raise SourceSecurityError("feed XML must not contain a DTD or entity")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise SourceFetchError(f"feed XML could not be parsed: {exc}") from exc
    root_name = _local_name(root.tag)
    if root_name == "rss":
        nodes = [node for node in root.iter() if _local_name(node.tag) == "item"]
    elif root_name == "feed":
        nodes = [node for node in root.iter() if _local_name(node.tag) == "entry"]
    else:
        raise SourceFetchError("feed root must be RSS or Atom")
    entries: list[FeedEntry] = []
    for node in nodes[:_MAX_ENTRIES]:
        title = _child_text(node, "title")
        link = _entry_link(node)
        if not title or not link:
            continue
        entries.append(
            FeedEntry(
                title=title,
                link=link,
                description=_child_text(node, "description")
                or _child_text(node, "summary"),
                published=_child_text(node, "pubDate")
                or _child_text(node, "published")
                or _child_text(node, "updated"),
                external_id=_child_text(node, "guid") or _child_text(node, "id"),
            )
        )
    return entries


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
