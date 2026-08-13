"""Bounded HTTP client for untrusted job-source URLs."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit

import httpx

from biojob.sources.base import SourceFetchError, SourceSecurityError


_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_USER_AGENT = "BioJob-Agent/0.1 (local desktop job discovery)"
_CHARSET_PATTERN = re.compile(r"charset\s*=\s*['\"]?([^;'\"\s]+)", re.I)
_TUN_SYNTHETIC_NETWORK = ipaddress.ip_network("198.18.0.0/15")


@dataclass(frozen=True)
class SafeHttpResponse:
    """A fully buffered response that has passed BioJob bounds."""

    url: str
    content: bytes
    content_type: str
    encoding: str

    @property
    def text(self) -> str:
        try:
            return self.content.decode(self.encoding, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")


class SafeHttpClient:
    """Fetch public HTTP(S) content with SSRF and size protections."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        resolver: Callable[[str], Iterable[str]] | None = None,
        timeout_seconds: float = 15.0,
        max_redirects: int = 5,
        max_body_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self.client = client
        self.resolver = resolver or _resolve_hostname
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self.max_body_bytes = max_body_bytes
        if timeout_seconds <= 0 or max_redirects < 0 or max_body_bytes <= 0:
            raise ValueError("HTTP safety bounds must be positive")

    def validate_external_link(self, url: str) -> str:
        """Validate a user-clicked HTTP(S) link without resolving or fetching it."""
        validated, _hostname = _validate_http_url_syntax(url)
        return validated

    def validate_public_url(
        self, url: str, *, reviewed_hosts: frozenset[str] = frozenset()
    ) -> str:
        url, hostname = _validate_http_url_syntax(url)
        normalized_reviewed_hosts = _normalize_reviewed_hosts(reviewed_hosts)
        hostname_is_reviewed = _normalize_hostname(hostname) in normalized_reviewed_hosts
        addresses = _literal_or_resolved_addresses(hostname, self.resolver)
        if not addresses:
            raise SourceSecurityError("source hostname did not resolve")
        for address in addresses:
            try:
                parsed_address = ipaddress.ip_address(address)
            except ValueError as exc:
                raise SourceSecurityError(
                    "source resolver returned an invalid IP"
                ) from exc
            if parsed_address in _TUN_SYNTHETIC_NETWORK and hostname_is_reviewed:
                continue
            if not parsed_address.is_global:
                raise SourceSecurityError(
                    "source hostname must resolve only to public addresses"
                )
        return url

    def get(
        self, url: str, *, reviewed_hosts: frozenset[str] = frozenset()
    ) -> SafeHttpResponse:
        normalized_reviewed_hosts = _normalize_reviewed_hosts(reviewed_hosts)
        if self.client is not None:
            return self._get_with_client(self.client, url, normalized_reviewed_hosts)
        with httpx.Client(trust_env=False) as client:
            return self._get_with_client(client, url, normalized_reviewed_hosts)

    def _get_with_client(
        self, client: httpx.Client, url: str, reviewed_hosts: frozenset[str]
    ) -> SafeHttpResponse:
        current_url = url
        redirects = 0
        while True:
            current_url = self.validate_public_url(
                current_url, reviewed_hosts=reviewed_hosts
            )
            try:
                with client.stream(
                    "GET",
                    current_url,
                    headers={"User-Agent": _USER_AGENT, "Accept": "*/*"},
                    timeout=self.timeout_seconds,
                    follow_redirects=False,
                ) as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            raise SourceFetchError(
                                "source redirect is missing a Location header"
                            )
                        if redirects >= self.max_redirects:
                            raise SourceFetchError("source redirect limit exceeded")
                        current_url = urljoin(str(response.url), location)
                        redirects += 1
                        continue
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        raise SourceFetchError(
                            f"source returned HTTP {response.status_code}"
                        ) from exc
                    declared_size = response.headers.get("content-length")
                    if declared_size is not None:
                        try:
                            if int(declared_size) > self.max_body_bytes:
                                raise SourceFetchError("source response is too large")
                        except ValueError:
                            pass
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > self.max_body_bytes:
                            raise SourceFetchError("source response is too large")
                        chunks.append(chunk)
                    raw_content_type = response.headers.get("content-type", "")
                    content_type = raw_content_type.split(";", 1)[0].strip().lower()
                    encoding_match = _CHARSET_PATTERN.search(raw_content_type)
                    encoding = encoding_match.group(1) if encoding_match else "utf-8"
                    return SafeHttpResponse(
                        url=str(response.url),
                        content=b"".join(chunks),
                        content_type=content_type,
                        encoding=encoding,
                    )
            except SourceFetchError:
                raise
            except httpx.HTTPError as exc:
                raise SourceFetchError(f"source request failed: {exc}") from exc


def _validate_http_url_syntax(url: str) -> tuple[str, str]:
        if not isinstance(url, str) or not url.strip():
            raise SourceSecurityError("source URL must be a non-empty string")
        if any(ord(character) < 32 or ord(character) == 127 for character in url):
            raise SourceSecurityError("source URL contains control characters")
        url = url.strip()
        try:
            parsed = urlsplit(url)
            hostname = parsed.hostname
            parsed.port
        except ValueError as exc:
            raise SourceSecurityError("source URL is malformed") from exc
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise SourceSecurityError(
                "source URL must be absolute public HTTP(S) without user info"
            )
        return url, hostname


def _normalize_hostname(hostname: str) -> str:
    try:
        return hostname.rstrip(".").encode("idna").decode("ascii").casefold()
    except UnicodeError as exc:
        raise SourceSecurityError("source hostname is malformed") from exc


def _normalize_reviewed_hosts(hostnames: frozenset[str]) -> frozenset[str]:
    if not isinstance(hostnames, frozenset) or not all(
        isinstance(hostname, str) and hostname for hostname in hostnames
    ):
        raise SourceSecurityError("reviewed source hosts are invalid")
    return frozenset(_normalize_hostname(hostname) for hostname in hostnames)


def _resolve_hostname(hostname: str) -> list[str]:
    try:
        return sorted({
            str(item[4][0])
            for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        })
    except OSError as exc:
        raise SourceFetchError(f"source hostname resolution failed: {exc}") from exc


def _literal_or_resolved_addresses(
    hostname: str, resolver: Callable[[str], Iterable[str]]
) -> list[str]:
    try:
        return [str(ipaddress.ip_address(hostname))]
    except ValueError:
        pass
    try:
        return list(resolver(hostname))
    except SourceFetchError:
        raise
    except Exception as exc:
        raise SourceFetchError(f"source hostname resolution failed: {exc}") from exc
